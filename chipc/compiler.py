import concurrent.futures as cf
import itertools
import os
import signal
from collections import OrderedDict
from os import path
from pathlib import Path

import psutil
from jinja2 import Environment
from jinja2 import FileSystemLoader
from jinja2 import StrictUndefined

from chipc import sketch_utils
from chipc import z3_utils
from chipc.mode import Mode
from chipc.sketch_code_generator import SketchCodeGenerator
from chipc.utils import get_hole_bit_width
from chipc.utils import get_hole_value_assignments
from chipc.utils import get_num_pkt_fields
from chipc.utils import get_state_group_info


def kill_child_processes(parent_pid, sig=signal.SIGTERM):
    try:
        parent = psutil.Process(parent_pid)
    except psutil.NoSuchProcess:
        return
    children = parent.children(recursive=True)
    for process in children:
        try:
            process.send_signal(sig)
            print('send_signal killed a child process', process)
        except psutil.NoSuchProcess as e:
            print("send_signal didn't have any effect because process didn't"
                  'exist')
            print(e)


class Compiler:
    def __init__(self, spec_filename, stateful_alu_filename,
                 stateless_alu_filename, num_pipeline_stages,
                 num_alus_per_stage, sketch_name, parallel_sketch,
                 constant_set, synthesized_allocation=False,
                 output_packet_fields=[],
                 output_state_groups=[],
                 input_packet_fields=[]):
        self.spec_filename = spec_filename
        self.stateful_alu_filename = stateful_alu_filename
        self.stateless_alu_filename = stateless_alu_filename
        self.num_pipeline_stages = num_pipeline_stages
        self.num_alus_per_stage = num_alus_per_stage
        self.sketch_name = sketch_name
        self.parallel_sketch = parallel_sketch
        self.constant_set = constant_set
        self.synthesized_allocation = synthesized_allocation

        program_content = Path(spec_filename).read_text()
        self.num_fields_in_prog = get_num_pkt_fields(program_content)
        self.num_state_groups = len(get_state_group_info(program_content))

        if not input_packet_fields:
            assert self.num_fields_in_prog <= num_alus_per_stage, (
                'Number of fields in program %d is greater than number of '
                'alus per stage %d. Try increasing '
                'number of alus per stage.' % (
                    self.num_fields_in_prog, num_alus_per_stage))
        else:
            assert len(input_packet_fields) <= num_alus_per_stage, (
                'Number of input fields in program %d is'
                'greater than number of alus per stage %d. Try increasing '
                'number of alus per stage.' % (
                    len(input_packet_fields), num_alus_per_stage))
            # Guarantee that # of output_packet_fields is less than or equal
            # to the num_alus_per_stage
            if output_packet_fields is not None:
                assert len(output_packet_fields) <= num_alus_per_stage, (
                    'Number of checked fields in program %d is '
                    'greater than number of alus per stage %d. '
                    'Try increasing number of alus per stage.' % (
                        len(output_packet_fields), num_alus_per_stage))

        # Initialize jinja2 environment for templates
        self.jinja2_env = Environment(
            loader=FileSystemLoader(
                [path.join(path.dirname(__file__), './templates'),
                 path.join(os.getcwd(),
                           stateless_alu_filename[
                               :stateless_alu_filename.rfind('/')]),
                 '.', '/']),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True)

        if not output_packet_fields and not output_state_groups:
            output_packet_fields = list(range(self.num_fields_in_prog))
            output_state_groups = list(range(self.num_state_groups))
        elif not output_packet_fields and output_state_groups:
            output_packet_fields = []
        elif output_packet_fields and not output_state_groups:
            output_state_groups = []

        # Differentiate between using default pkt input vs. specify pkt input
        if not input_packet_fields:
            input_packet_fields = list(range(self.num_fields_in_prog))

        # Create an object for sketch generation
        self.sketch_code_generator = SketchCodeGenerator(
            sketch_name=sketch_name,
            num_pipeline_stages=num_pipeline_stages,
            num_alus_per_stage=num_alus_per_stage,
            num_phv_containers=num_alus_per_stage,
            num_state_groups=self.num_state_groups,
            num_fields_in_prog=self.num_fields_in_prog,
            output_packet_fields=output_packet_fields,
            output_state_groups=output_state_groups,
            jinja2_env=self.jinja2_env,
            stateful_alu_filename=stateful_alu_filename,
            stateless_alu_filename=stateless_alu_filename,
            constant_set=constant_set,
            synthesized_allocation=synthesized_allocation,
            input_packet_fields=input_packet_fields)

    def update_constants_for_synthesis(self, constant_set):
        # Join the values in constant_set to get constant_array in sketch.
        new_constant_set_str = '{' + ','.join(constant_set) + '}'

        # Use string format to create constant_arr_def_
        self.sketch_code_generator.constant_arr_def_ = \
            'int[{}]'.format(str(len(constant_set))) + \
            'constant_vector = {};\n\n'.format(new_constant_set_str)
        self.sketch_code_generator.constant_arr_size_ = get_hole_bit_width(
            len(constant_set))

    def single_codegen_run(self, compiler_input):
        additional_constraints = compiler_input[0]
        additional_testcases = compiler_input[1]
        sketch_file_name = compiler_input[2]

        """Codegeneration"""
        codegen_code = self.sketch_code_generator.generate_sketch(
            spec_filename=self.spec_filename,
            mode=Mode.CODEGEN,
            synthesized_allocation=self.synthesized_allocation,
            additional_constraints=additional_constraints,
            additional_testcases=additional_testcases)

        # Create file and write sketch_harness into it.
        with open(sketch_file_name, 'w') as sketch_file:
            sketch_file.write(codegen_code)

        # Call sketch on it
        print('Total number of hole bits is',
              self.sketch_code_generator.total_hole_bits_)
        print('Sketch file is', sketch_file_name)
        assert (self.parallel_sketch in [True, False])
        (ret_code, output) = sketch_utils.synthesize(
            sketch_file_name,
            bnd_inbits=2,
            slv_seed=1,
            slv_parallel=self.parallel_sketch)

        # Store sketch output
        with open(sketch_file_name[:sketch_file_name.find('.sk')] +
                  '_output.txt', 'w') as output_file:
            output_file.write(output)
        if (ret_code == 0):
            holes_to_values = get_hole_value_assignments(
                self.sketch_code_generator.hole_names_, output)
        else:
            holes_to_values = OrderedDict()
        return (ret_code, output, holes_to_values)

    def serial_codegen(self, iter_cnt=1, additional_constraints=[],
                       additional_testcases=''):
        return self.single_codegen_run((additional_constraints,
                                        additional_testcases,
                                        self.sketch_name +
                                        '_codegen_iteration_' +
                                        str(iter_cnt) + '.sk'))

    def parallel_codegen(self,
                         additional_constraints=[],
                         additional_testcases=''):
        # For each state_group, pick a pipeline_stage exhaustively.
        # Note that some of these assignments might be infeasible, but that's
        # OK. Sketch will reject these anyway.
        count = 0
        compiler_output = None
        compiler_inputs = []
        for assignment in itertools.product(list(
            range(self.num_pipeline_stages)),
                repeat=self.num_state_groups):
            constraint_list = additional_constraints.copy()
            count = count + 1
            print('Now in assignment # ', count, ' assignment is ', assignment)
            for state_group in range(self.num_state_groups):
                assigned_stage = assignment[state_group]
                for stage in range(self.num_pipeline_stages):
                    if (stage == assigned_stage):
                        constraint_list += [
                            self.sketch_name + '_salu_config_' +
                            str(stage) + '_' + str(state_group) + ' == 1'
                        ]
                    else:
                        constraint_list += [
                            self.sketch_name + '_salu_config_' +
                            str(stage) + '_' + str(state_group) + ' == 0'
                        ]
            compiler_inputs += [
                (constraint_list, additional_testcases,
                 self.sketch_name + '_' + str(count) + '_codegen.sk')
            ]

        with cf.ProcessPoolExecutor(max_workers=count) as executor:
            futures = []
            for compiler_input in compiler_inputs:
                futures.append(
                    executor.submit(self.single_codegen_run, compiler_input))

            for f in cf.as_completed(futures):
                compiler_output = f.result()
                if (compiler_output[0] == 0):
                    print('Success')
                    # TODO: Figure out the right way to do this in the future.
                    executor.shutdown(wait=False)
                    kill_child_processes(os.getpid())
                    return compiler_output
                else:
                    print('One run failed, waiting for others.')
        return compiler_output

    def verify(self, hole_assignments, input_bits, iter_cnt=1):
        """Verify hole value assignments for the sketch with a specific input
        bit lengths with z3.

        Returns:
            A tuple of two dicts from string to ints, where the first one
            represents counterexamples for packet variables and the second for
            state group variables.
            If the hole value assignments work for the input_bits, returns
            a tuple of two empty dicts.
        """
        # Check all holes have values.
        for hole in self.sketch_code_generator.hole_names_:
            assert hole in hole_assignments

        # Generate a sketch file to verify the hole value assignments with
        # the specified input bit lengths.
        sketch_to_verify = self.sketch_code_generator.generate_sketch(
            spec_filename=self.spec_filename,
            mode=Mode.VERIFY,
            synthesized_allocation=self.synthesized_allocation,
            hole_assignments=hole_assignments
        )

        # Write sketch to a file.
        file_basename = self.sketch_name + '_verify_iter_' + str(iter_cnt)
        sketch_filename = file_basename + '.sk'
        Path(sketch_filename).write_text(sketch_to_verify)

        sketch_ir = sketch_utils.generate_ir(sketch_filename)

        z3_formula = z3_utils.get_z3_formula(sketch_ir, input_bits)

        return z3_utils.generate_counterexamples(z3_formula)
