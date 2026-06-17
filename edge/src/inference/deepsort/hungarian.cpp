/* SPDX-License-Identifier: MIT */
/*
 * Hungarian Algorithm — 最小代价分配
 *
 * 纯 C++ 实现，不依赖 Eigen 稀疏矩阵。
 * O(n^3) 时间复杂度。
 */

#include "hungarian.h"
#include <cfloat>
#include <cmath>

Hungarian::Hungarian(int rows, int cols)
    : _n_rows(rows), _n_cols(cols)
{
    _assignment.resize(rows, -1);
    _cost = Eigen::MatrixXf::Zero(rows, std::max(cols, rows));
}

void Hungarian::solve(const Eigen::MatrixXf &cost_matrix)
{
    int n = std::max(_n_rows, _n_cols);

    /* 扩展为方阵 */
    _cost = Eigen::MatrixXf::Constant(n, n, 0.0f);
    _cost.block(0, 0, _n_rows, _n_cols) = cost_matrix;

    /* 行减最小值 */
    for (int i = 0; i < n; i++) {
        float min_val = _cost.row(i).minCoeff();
        _cost.row(i).array() -= min_val;
    }

    /* 列减最小值 */
    for (int j = 0; j < n; j++) {
        float min_val = _cost.col(j).minCoeff();
        _cost.col(j).array() -= min_val;
    }

    /* 初始化标记 */
    std::vector<int> row_cover(n, 0);
    std::vector<int> col_cover(n, 0);
    _assignment.assign(n, -1);

    /* 贪心初始匹配 */
    for (int i = 0; i < n; i++) {
        for (int j = 0; j < n; j++) {
            if (std::abs(_cost(i, j)) < 1e-6f && !col_cover[j]) {
                _assignment[i] = j;
                col_cover[j] = 1;
                break;
            }
        }
    }

    /* 主循环: 增加匹配数 */
    for (int step = 0; step < n; step++) {
        /* 找未分配行 */
        int start_row = -1;
        for (int i = 0; i < n; i++) {
            if (_assignment[i] == -1) {
                start_row = i;
                break;
            }
        }
        if (start_row == -1) break;  /* 全部匹配 */

        /* BFS 找增广路径 */
        std::vector<int> parent_row(n, -1);
        std::vector<int> parent_col(n, -1);
        std::vector<float> min_slack(n, FLT_MAX);
        std::vector<int> visited_row(n, 0);
        std::vector<int> visited_col(n, 0);

        visited_row[start_row] = 1;

        int matched_col = -1;
        int matched_row = start_row;

        while (matched_col == -1) {
            /* 更新最小slack */
            float delta = FLT_MAX;
            for (int j = 0; j < n; j++) {
                if (!visited_col[j]) {
                    float slack = _cost(matched_row, j);
                    if (slack < min_slack[j]) {
                        min_slack[j] = slack;
                        parent_col[j] = matched_row;
                    }
                    if (min_slack[j] < delta) {
                        delta = min_slack[j];
                        matched_col = j;
                    }
                }
            }

            /* 减 delta */
            for (int i = 0; i < n; i++) {
                if (visited_row[i])
                    _cost.row(i).array() -= delta;
            }
            for (int j = 0; j < n; j++) {
                if (visited_col[j])
                    _cost.col(j).array() += delta;
            }

            /* 检查是否找到零 */
            float zero_slack = 1e-6f;
            for (int j = 0; j < n; j++) {
                if (!visited_col[j] && min_slack[j] < zero_slack) {
                    matched_col = j;
                    matched_row = parent_col[j];
                    break;
                }
            }

            if (matched_col == -1) continue;

            /* 检查该列是否已有分配 */
            int assigned_row = -1;
            for (int i = 0; i < n; i++) {
                if (_assignment[i] == matched_col) {
                    assigned_row = i;
                    break;
                }
            }

            if (assigned_row == -1) {
                /* 找到增广路径，增广 */
                int cur_col = matched_col;
                int cur_row = matched_row;
                while (cur_row != -1) {
                    int next_col = _assignment[cur_row];
                    _assignment[cur_row] = cur_col;
                    cur_col = next_col;
                    cur_row = (cur_col >= 0) ? parent_row[cur_col] : -1;
                }
            } else {
                /* 继续 BFS */
                visited_row[assigned_row] = 1;
                visited_col[matched_col] = 1;
                parent_row[matched_col] = matched_row;
                matched_row = assigned_row;
                matched_col = -1;
            }
        }
    }
}

int Hungarian::assignment(int row) const
{
    if (row < 0 || row >= _n_rows) return -1;
    int col = _assignment[row];
    return (col < _n_cols) ? col : -1;
}