(assert (forall ((pkt_1_1_0  Int  )) (let ((_n0 pkt_1_1_0 ))
(let ((_n1 (+   _n0   _n0 ) ))
(let ((_n2 2 ))
(let ((_n3 (*   _n0   _n2 ) ))
(let ((_n4 (=   _n3   _n1 ) ))
(implies  (and (>= pkt_1_1_0 0) (< pkt_1_1_0 4 ))    _n4  ))))))))
(check-sat)
(get-model)
(exit)
