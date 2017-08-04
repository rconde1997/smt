"""
Author: Dr. John T. Hwang         <hwangjt@umich.edu>

"""

from __future__ import division

import numpy as np
from scipy.sparse import csc_matrix
from smt.methods.sm import SM

from smt.utils.linear_solvers import get_solver
from smt.utils.caching import cached_operation

from smt.methods.rbfclib import PyRBF


class RBF(SM):

    """
    Radial basis function interpolant with global polynomial trend.
    """

    def initialize(self):
        super(RBF, self).initialize()
        declare = self.options.declare
        supports = self.supports

        declare('d0', 1.0, types=(int, float, list, np.ndarray),
                desc='basis function scaling parameter in exp(-d^2 / d0^2)')
        declare('poly_degree', -1,types=int, values=(-1, 0, 1),
                desc='-1 means no global polynomial, 0 means constant, 1 means linear trend')
        declare('data_dir', values=None, types=str,
                desc='Directory for loading / saving cached data; None means do not save or load')
        declare('reg', 1e-10, types=(int, float),
                desc='Regularization coeff.')
        declare('max_print_depth', 5, types=int,
                desc='Maximum depth (level of nesting) to print operation descriptions and times')

        supports['derivatives'] = True

        self.name = 'RBF'

    def _initialize(self):
        options = self.options

        nx = self.training_points[None][0][0].shape[1]
        if isinstance(options['d0'], (int, float)):
            options['d0'] = [options['d0']] * nx
        options['d0'] = np.atleast_1d(options['d0'])

        self.printer.max_print_depth = options['max_print_depth']

        num = {}
        # number of inputs and outputs
        num['x'] = self.training_points[None][0][0].shape[1]
        num['y'] = self.training_points[None][0][1].shape[1]
        # number of radial function terms
        num['radial'] = self.training_points[None][0][0].shape[0]
        # number of polynomial terms
        if options['poly_degree'] == -1:
            num['poly'] = 0
        elif options['poly_degree'] == 0:
            num['poly'] = 1
        elif options['poly_degree'] == 1:
            num['poly'] = 1 + num['x']
        num['dof'] = num['radial'] + num['poly']

        self.num = num

        nt = self.training_points[None][0][0].shape[0]
        xt, yt = self.training_points[None][0]

        self.rbfc = PyRBF()
        self.rbfc.setup(
            num['x'], nt, num['dof'], options['poly_degree'], options['d0'], xt.flatten())

    def _new_train(self):
        num = self.num

        xt, yt = self.training_points[None][0]
        jac = np.empty(num['radial'] * num['dof'])
        self.rbfc.compute_jac(num['radial'], xt.flatten(), jac)
        jac = jac.reshape((num['radial'], num['dof']))

        mtx = np.zeros((num['dof'], num['dof']))
        mtx[:num['radial'], :] = jac
        mtx[:, :num['radial']] = jac.T
        mtx[np.arange(num['radial']), np.arange(num['radial'])] += self.options['reg']

        rhs = np.zeros((num['dof'], num['y']))
        rhs[:num['radial'], :] = yt

        sol = np.zeros((num['dof'], num['y']))

        solver = get_solver('dense-lu')
        with self.printer._timed_context('Initializing linear solver'):
            solver._initialize(mtx, self.printer)

        for ind_y in range(rhs.shape[1]):
            with self.printer._timed_context('Solving linear system (col. %i)' % ind_y):
                solver._solve(rhs[:, ind_y], sol[:, ind_y], ind_y=ind_y)

        self.sol = sol

    def _train(self):
        """
        Train the model
        """
        self._initialize()

        tmp = self.rbfc
        self.rbfc = None

        inputs = {'self': self}
        with cached_operation(inputs, self.options['data_dir']) as outputs:
            self.rbfc = tmp

            if outputs:
                self.sol = outputs['sol']
            else:
                self._new_train()
                outputs['sol'] = self.sol

    def _predict_values(self, x):
        """
        Evaluates the model at a set of points.

        Arguments
        ---------
        x : np.ndarray [n_evals, dim]
            Evaluation point input variable values

        Returns
        -------
        y : np.ndarray
            Evaluation point output variable values
        """
        n = x.shape[0]
        num = self.num

        jac = np.empty(n * num['dof'])
        self.rbfc.compute_jac(n, x.flatten(), jac)
        jac = jac.reshape((n, num['dof']))

        y = jac.dot(self.sol)
        return y

    def _predict_derivatives(self, x, kx):
        """
        Evaluates the derivatives at a set of points.

        Arguments
        ---------
        x : np.ndarray [n_evals, dim]
            Evaluation point input variable values
        kx : int
            The 0-based index of the input variable with respect to which derivatives are desired.

        Returns
        -------
        dy_dx : np.ndarray
            Derivative values.
        """
        n = x.shape[0]
        num = self.num

        jac = np.empty(n * num['dof'])
        self.rbfc.compute_jac_derivs(n, kx, x.flatten(), jac)
        jac = jac.reshape((n, num['dof']))

        dy_dx = jac.dot(self.sol)
        return dy_dx
