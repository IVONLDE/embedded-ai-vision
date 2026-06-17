/* SPDX-License-Identifier: MIT */
/*
 * Hungarian Algorithm — Header
 */

#ifndef HUNGARIAN_H
#define HUNGARIAN_H

#include <vector>
#include <Eigen/Dense>

class Hungarian {
public:
    Hungarian(int rows, int cols);
    void solve(const Eigen::MatrixXf &cost_matrix);
    int assignment(int row) const;

private:
    int _n_rows, _n_cols;
    std::vector<int> _assignment;
    Eigen::MatrixXf _cost;
};

#endif /* HUNGARIAN_H */