"""Repeated Solver"""

from pathlib import Path
import re
import subprocess
import sys
import time

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from sketch_generator import SketchGenerator
from utils import get_num_pkt_fields_and_state_groups

if (len(sys.argv) < 9):  # This part may need change with the chipmunk.py file
    print(
        "Usage: python3 " + sys.argv[0] +
        " <program file> <alu file> <number of pipeline stages> " + \
        "<number of stateless/stateful ALUs per stage> <codegen/optverify> " + \
        "<sketch_name (w/o file extension)> <parallel/serial> " + \
        "<counter_example_mode/hole_elimination_mode>"
    )
    sys.exit(1)
else:
    start = time.time()
    program_file = str(sys.argv[1])
    (num_fields_in_prog, num_state_groups) = get_num_pkt_fields_and_state_groups(
        Path(program_file).read_text())
    alu_file = str(sys.argv[2])
    num_pipeline_stages = int(sys.argv[3])
    num_alus_per_stage = int(sys.argv[4])
    num_phv_containers = num_alus_per_stage
    mode = str(sys.argv[5])
    # Now I want to make sure the mode is codegen
    assert mode == "codegen"
    sketch_name = str(sys.argv[6])
    parallel_or_serial = str(sys.argv[7])
    version = str(sys.argv[8])
    assert (version == "counter_example_mode") or (
        version == "hole_elimination_mode")

# Initialize jinja2 environment for templates
env = Environment(
    loader=FileSystemLoader('./templates'), undefined=StrictUndefined)

# Create an object for sketch generation
sketch_generator = SketchGenerator(
    sketch_name=sketch_name,
    num_pipeline_stages=num_pipeline_stages,
    num_alus_per_stage=num_alus_per_stage,
    num_phv_containers=num_phv_containers,
    num_state_groups=num_state_groups,
    num_fields_in_prog=num_fields_in_prog,
    jinja2_env=env,
    alu_file=alu_file)

# Create stateless and stateful ALUs, operand muxes for stateful ALUs, and output muxes.
alu_definitions = sketch_generator.generate_alus()
stateful_operand_mux_definitions = sketch_generator.generate_stateful_operand_muxes(
)
output_mux_definitions = sketch_generator.generate_output_muxes()

# Create allocator to ensure each state var is assigned to exactly stateful ALU and vice versa.
sketch_generator.generate_state_allocator()

#Step1: run chipmunk to get the codegen
(ret_code, output) = subprocess.getstatusoutput(
    "python3 chipmunk.py " + program_file + " " + alu_file + " " +
    str(num_pipeline_stages) + " " + str(num_alus_per_stage) + " " + mode +
    " " + sketch_name + " " + parallel_or_serial)
if (ret_code != 0):
    print("failed")
    end = time.time()
    print("total time in seconds: ", end - start)
    sys.exit(1)
else:
    # Generate the result file
    with open("/tmp/" + sketch_name + "_result.holes", "w") as result_file:
        result_file.write(output)
    # Step2: run sol_verify.py
    (ret_code, output) = subprocess.getstatusoutput(
        "python3 sol_verify.py " + sketch_name + "_codegen.sk" + " " +
        "/tmp/" + sketch_name + "_result.holes ")
    if (ret_code == 0):
        print("success")
        end = time.time()
        print("total time in seconds: ", end - start)
        sys.exit(0)
    else:
        print("failed for larger size and need repeated testing by sketch")
        # start to repeated run sketch until get the final result
        original_sketch_file_string = Path(sketch_name +
                                           "_codegen.sk").read_text()
        count = 0
        while (1):
            if (version == "hole_elimination_mode"):
                hole_value_file_string = Path(
                    "/tmp/" + sketch_name + "_result.holes").read_text()
                begin_pos = hole_value_file_string.find('int')
                end_pos = hole_value_file_string.rfind(';')
                hole_value_file_string = hole_value_file_string[begin_pos:
                                                                end_pos + 1]
                #rearrange the format (int x=1; int y=2;) to (x==1 && y==2 && 1)
                hole_value_file_string = hole_value_file_string.replace(
                    "int", "")
                hole_value_file_string = hole_value_file_string.replace(
                    "=", "==")
                hole_value_file_string = hole_value_file_string.replace(
                    ";", "&&")
                hole_value_file_string = hole_value_file_string + "1"
                #find the position of harness
                begin_pos = original_sketch_file_string.find('harness')
                begin_pos = original_sketch_file_string.find(
                    'assert', begin_pos)
                original_sketch_file_string = original_sketch_file_string[
                    0:
                    begin_pos] + "assert(!(" + hole_value_file_string + "));\n" + original_sketch_file_string[
                        begin_pos:]
            else:
                # Find the position of harness
                begin_pos = original_sketch_file_string.find('harness')
                begin_pos = original_sketch_file_string.find(
                    'assert', begin_pos)

                # Add function assert here
                if (count == 0):
                    (ret_code_sketch_with_counter_example,
                     output_with_counter_example) = subprocess.getstatusoutput(
                         "sketch -V 3 --debug-cex --bnd-inbits=10 " +
                         sketch_name + "_codegen_with_hole_value.sk")
                else:
                    (ret_code_sketch_with_counter_example,
                     output_with_counter_example) = subprocess.getstatusoutput(
                         "sketch -V 3 --debug-cex --bnd-inbits=10 " + "/tmp/" +
                         sketch_name + "_new_sketch_with_hole_value.sk")
                input_values = re.findall("has value \d+= " + '\((\d+)\)',
                                          output_with_counter_example)
                hits_pkt = re.findall("pkt_\d+", output_with_counter_example)
                hits_state = re.findall("state_\d+",
                                        output_with_counter_example)
                print(input_values)
                print("pkt: ", hits_pkt)
                print("state: ", hits_state)
                counter_example_definition = "|StateAndPacket| x_" + str(
                    count) + " = |StateAndPacket|(\n"
                for i in range(len(hits_pkt)):
                    counter_example_definition += hits_pkt[
                        i] + " = " + input_values[i] + ','
                for i in range(len(hits_state) - 1):
                    counter_example_definition += hits_state[
                        i] + " = " + input_values[len(hits_pkt) + i] + ','
                counter_example_definition += hits_state[
                    len(hits_state) -
                    1] + " = " + input_values[len(input_values) - 1] + ");\n"

                counter_example_assert = "assert pipeline(" + "x_" + str(
                    count) + ")" + " == " + "program(" + "x_" + str(
                        count) + ");\n"
                original_sketch_file_string = original_sketch_file_string[
                    0:
                    begin_pos] + counter_example_definition + counter_example_assert + original_sketch_file_string[
                        begin_pos:]

            new_sketch = open("/tmp/" + sketch_name + "_new_sketch.sk", "w")
            new_sketch.write(original_sketch_file_string)
            new_sketch.close()
            (ret_code1, output) = subprocess.getstatusoutput(
                "sketch -V 3 --bnd-inbits=2 --bnd-int-range=50 " +
                new_sketch.name)
            print("Iteration #" + str(count))
            hole_value_string = ""
            #Failed      print("Hello1")
            if (ret_code1 == 0):
                hole_value_file = open("/tmp/" + sketch_name + "_result.holes",
                                       "w")
                for hole_name in sketch_generator.hole_names_:
                    hits = re.findall("(" + hole_name + ")__" + "\w+ = (\d+)",
                                      output)
                    if (len(hits) != 1):
                        print(hits)
                        print(hole_name)
                    else:
                        hole_value_string += "int " + hits[0][
                            0] + " = " + hits[0][1] + ";"
                hole_value_file.write(hole_value_string)
                hole_value_file.close()
                (ret_code, output) = subprocess.getstatusoutput(
                    "python3 sol_verify.py " + "/tmp/" + sketch_name +
                    "_new_sketch.sk" + " " + "/tmp/" + sketch_name +
                    "_result.holes ")
                if (ret_code == 0):
                    print("finally succeed")
                    end = time.time()
                    print("total time in seconds: ", end - start)
                    exit(0)
                else:
                    count = count + 1
                    continue
            else:
                print("finally failed")
                end = time.time()
                print("total time in seconds: ", end - start)
                print("total while loop: ", count)
                sys.exit(1)
