from __future__ import annotations

from copy import deepcopy as pydeepcopy
from typing import Optional, Dict

from pyjuice.nodes import CircuitNodes, InputNodes, ProdNodes, SumNodes
from pyjuice.utils import BitSet


def deepcopy(root_nodes: CircuitNodes, tie_params: bool = False, 
             var_mapping: Optional[Dict[int,int]] = None):
    old2new = dict()
    tied_ns_pairs = []

    def dfs(ns: CircuitNodes):
        if ns in old2new:
            return

        # Recursively traverse children
        if ns.is_sum() or ns.is_prod():
            for cs in ns.chs:
                dfs(cs)

        new_chs = [old2new[cs] for cs in ns.chs]

        if not tie_params and ns.is_tied():
            tied_ns_pairs.append((ns, ns.get_source_ns()))

        if ns.is_sum():
            if not tie_params:
                new_ns = SumNodes(
                    ns.num_nodes,
                    new_chs,
                    ns.edge_ids.clone()
                )
                params = ns.get_params()
                if params is not None:
                    new_ns.set_params(params.clone())
            else:
                new_ns = ns.duplicate(*new_chs, tie_params = True)
            
        elif ns.is_prod():
            new_ns = ProdNodes(
                ns.num_nodes,
                new_chs,
                ns.edge_ids.clone()
            )
            
        else:
            assert ns.is_input()
            if not tie_params:
                new_ns = InputNodes(
                    ns.num_nodes,
                    pydeepcopy(ns.scope),
                    pydeepcopy(ns.dist)
                )
                params = ns.get_params()
                if params is not None:
                    new_ns.set_params(params.clone())
            else:
                if var_mapping is not None:
                    ns_scope = ns.scope
                    scope = BitSet()
                    for v in ns_scope:
                        assert v in var_mapping, f"Variable {v} not found in `var_mapping`."
                        scope.add(var_mapping[v])
                else:
                    scope = pydeepcopy(ns.scope)

                new_ns = ns.duplicate(scope = scope, tie_params = True)

        old2new[ns] = new_ns

    dfs(root_nodes)

    for ns, source_ns in tied_ns_pairs:
        new_ns = old2new[ns]
        new_source_ns = old2new[source_ns]

        new_ns._source_node = new_source_ns

    return old2new[root_nodes]