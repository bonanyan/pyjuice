import torch
import numpy as np
from numba import njit
import math

from typing import Union, Optional


@njit()
def _partition_nodes_dp_simple_compiled(node_n_edges, dp, backtrace, max_num_groups, target_overhead):
    num_nodes = node_n_edges.shape[0]

    # Init
    for i in range(num_nodes):
        dp[i,1] = node_n_edges[i] * (i + 1)

    # Main DP
    target_n_group = max_num_groups
    for n_group in range(2, max_num_groups + 1):
        dp[0,n_group] = node_n_edges[0]
        backtrace[0,n_group] = 0
        for i in range(1, num_nodes):
            min_overhead = 2 ** 31 - 1
            best_idx = -1
            for j in range(i):
                curr_overhead = dp[j,n_group-1] + node_n_edges[i] * (i - j)
                if curr_overhead < min_overhead:
                    min_overhead = curr_overhead
                    best_idx = j

            dp[i,n_group] = min_overhead
            backtrace[i,n_group] = best_idx

        if dp[-1,n_group] < target_overhead:
            target_n_group = n_group
            break

    overhead = dp[-1,target_n_group]

    return overhead, target_n_group

@njit
def _backtrace_fn(partitions, backtrace, target_n_group, num_nodes):
    i = num_nodes - 1
    for n in range(target_n_group, 0, -1):
        partitions[n-1] = i
        i = backtrace[i,target_n_group]


def _partition_nodes_dp_simple(node_n_edges: np.ndarray, max_num_groups: int, target_overhead: Optional[int]):

    dp = np.zeros([node_n_edges.shape[0], max_num_groups + 1], dtype = np.int64)
    backtrace = np.zeros([node_n_edges.shape[0], max_num_groups + 1], dtype = np.int64)

    overhead, target_n_group = _partition_nodes_dp_simple_compiled(
        np.ascontiguousarray(node_n_edges), 
        np.ascontiguousarray(dp), 
        np.ascontiguousarray(backtrace),
        max_num_groups,
        target_overhead = 0 if target_overhead is None else target_overhead
    )

    # Backtrace
    partitions = np.zeros([target_n_group], dtype = np.int64)
    num_nodes = node_n_edges.shape[0]
    _backtrace_fn(partitions, backtrace, target_n_group, num_nodes)

    return np.unique(node_n_edges[partitions]), overhead


@njit
def _coalesce_fn(unique_vals, counts, keep_flag, unique_counts, tol_range):
    num_vals = unique_vals.shape[0]

    curr_keep_val = 0
    curr_count = 0
    curr_idx = -1
    for i in range(num_vals):
        if curr_idx == -1:
            curr_idx = i
            curr_keep_val = unique_vals[i]
            curr_count = counts[i]
        elif unique_vals[i] - curr_keep_val <= tol_range:
            curr_count += counts[i]
        else:
            keep_flag[i-1] = True
            unique_counts[i-1] = curr_count

            curr_idx = i
            curr_keep_val = unique_vals[i]
            curr_count = counts[i]

    if curr_idx != -1:
        keep_flag[num_vals-1] = True
        unique_counts[num_vals-1] = curr_count


def _coalesce(vals, tol_range = "auto"):
    unique_vals, counts = np.unique(vals, return_counts = True)
    keep_flag = np.zeros([unique_vals.shape[0]], dtype = bool)
    unique_counts = np.zeros([unique_vals.shape[0]], dtype = np.int64)

    if tol_range == "auto":
        tol_range = int(math.floor((unique_vals.max() - unique_vals.min()) / 1000))

    _coalesce_fn(
        np.ascontiguousarray(unique_vals), 
        np.ascontiguousarray(counts), 
        keep_flag, 
        unique_counts, 
        tol_range
    )

    return unique_vals[keep_flag], unique_counts[keep_flag]


@njit()
def _weighted_partition_nodes_dp_simple_compiled(node_n_edges, cum_counts, dp, backtrace, max_num_groups, target_overhead):
    num_nodes = node_n_edges.shape[0]

    # Init
    for i in range(num_nodes):
        dp[i,1] = node_n_edges[i] * cum_counts[i]

    # Main DP
    target_n_group = max_num_groups
    for n_group in range(2, max_num_groups + 1):
        dp[0,n_group] = node_n_edges[0] * cum_counts[0]
        backtrace[0,n_group] = 0
        for i in range(1, num_nodes):
            min_overhead = 2 ** 31 - 1
            best_idx = -1
            for j in range(i):
                curr_overhead = dp[j,n_group-1] + node_n_edges[i] * (cum_counts[i] - cum_counts[j])
                if curr_overhead < min_overhead:
                    min_overhead = curr_overhead
                    best_idx = j

            dp[i,n_group] = min_overhead
            backtrace[i,n_group] = best_idx

        if dp[-1,n_group] < target_overhead:
            target_n_group = n_group
            break

    overhead = dp[-1,target_n_group]

    return overhead, target_n_group


def _weighted_partition_nodes_dp_simple(node_n_edges: np.ndarray, counts: np.ndarray, max_num_groups: int, 
                                        target_overhead: Optional[int]):

    cum_counts = np.cumsum(counts)

    dp = np.zeros([node_n_edges.shape[0], max_num_groups + 1], dtype = np.int64)
    backtrace = np.zeros([node_n_edges.shape[0], max_num_groups + 1], dtype = np.int64)

    overhead, target_n_group = _weighted_partition_nodes_dp_simple_compiled(
        np.ascontiguousarray(node_n_edges),
        np.ascontiguousarray(cum_counts),
        np.ascontiguousarray(dp), 
        np.ascontiguousarray(backtrace),
        max_num_groups,
        target_overhead = 0 if target_overhead is None else target_overhead
    )

    # Backtrace
    partitions = np.zeros([target_n_group], dtype = np.int64)
    num_nodes = node_n_edges.shape[0]
    _backtrace_fn(partitions, backtrace, target_n_group, num_nodes)

    return np.unique(node_n_edges[partitions]), overhead


def partition_nodes_by_n_edges(node_n_edges: Union[np.ndarray, torch.Tensor], 
                               max_num_groups: Optional[int] = None, 
                               sparsity_tolerance: Optional[float] = None,
                               algorithm: str = "dp_with_coalesce"):

    if sparsity_tolerance is not None and sparsity_tolerance < 1e-6:
        sparsity_tolerance = None
        max_num_groups = 1

    if sparsity_tolerance is not None:
        assert sparsity_tolerance > 1e-6 and sparsity_tolerance <= 1.0
        if max_num_groups is None:
            max_num_groups = max(min(int(math.ceil(node_n_edges.shape[0] * sparsity_tolerance)), 16), 1)
    elif max_num_groups is None:
        max_num_groups = 1
    else:
        assert max_num_groups >= 1, "Should provide at least 1 group."

    if isinstance(node_n_edges, torch.Tensor):
        node_n_edges = node_n_edges.detach().cpu().numpy()

    total_num_edges = node_n_edges.sum()
    target_overhead = None if sparsity_tolerance is None else int(math.ceil(total_num_edges / sparsity_tolerance))

    if max_num_groups == 1:
        partitions = np.zeros([1], dtype = np.int64)
        partitions[0] = np.max(node_n_edges)
        return torch.from_numpy(partitions)

    # Sort in non-descending order
    node_n_edges = np.sort(node_n_edges)

    if algorithm == "dp_simple":
        group_sizes, overhead = _partition_nodes_dp_simple(node_n_edges, max_num_groups, target_overhead)

    elif algorithm == "dp_with_coalesce":
        unique_n_edges, counts = _coalesce(node_n_edges, tol_range = "auto")
        group_sizes, overhead = _weighted_partition_nodes_dp_simple(unique_n_edges, counts, max_num_groups, target_overhead)

    else:
        raise ValueError(f"Unknown algorithm {algorithm} for `partition_nodes_by_n_edges`.")

    if isinstance(group_sizes, np.ndarray):
        group_sizes = torch.from_numpy(group_sizes)

    return torch.sort(group_sizes).values