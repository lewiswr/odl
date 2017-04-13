# Copyright 2014-2016 The ODL development group
#
# This file is part of ODL.
#
# ODL is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# ODL is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with ODL.  If not, see <http://www.gnu.org/licenses/>.

"""Test analytical reconstruction methods."""

# Imports for common Python 2/3 codebase
from __future__ import print_function, division, absolute_import
from future import standard_library
standard_library.install_aliases()

# External
import pytest
import numpy as np

# Internal
import odl
import odl.tomo as tomo
from odl.util.testutils import skip_if_no_largescale, simple_fixture
from odl.tomo.util.testutils import (skip_if_no_astra, skip_if_no_astra_cuda,
                                     skip_if_no_skimage)

filter_type = simple_fixture(
    'filter_type', ['Ram-Lak', 'Shepp-Logan', 'Cosine', 'Hamming', 'Hann'])
frequency_scaling = simple_fixture(
    'frequency_scaling', [0.5, 0.9, 1.0])

# Find the valid projectors
# TODO: Add nonuniform once #671 is solved
projectors = [skip_if_no_astra('par2d astra_cpu uniform'),
              skip_if_no_astra('cone2d astra_cpu uniform'),
              skip_if_no_astra_cuda('par2d astra_cuda uniform'),
              skip_if_no_astra_cuda('cone2d astra_cuda uniform'),
              skip_if_no_astra_cuda('par3d astra_cuda uniform'),
              skip_if_no_astra_cuda('cone3d astra_cuda uniform'),
              skip_if_no_astra_cuda('helical astra_cuda uniform'),
              skip_if_no_skimage('par2d skimage uniform')]

projector_ids = ['geom={}, impl={}, angles={}'
                 ''.format(*p.args[1].split()) for p in projectors]


# bug in pytest (ignores pytestmark) forces us to do this this
largescale = " or not pytest.config.getoption('--largescale')"
projectors = [pytest.mark.skipif(p.args[0] + largescale, p.args[1])
              for p in projectors]


@pytest.fixture(scope="module", params=projectors, ids=projector_ids)
def projector(request):

    n_angles = 500
    dtype = 'float32'

    geom, impl, angle = request.param.split()

    if angle == 'uniform':
        apart = odl.uniform_partition(0, 2 * np.pi, n_angles)
    elif angle == 'random':
        # Linearly spaced with random noise
        min_pt = 2 * (2.0 * np.pi) / n_angles
        max_pt = (2.0 * np.pi) - 2 * (2.0 * np.pi) / n_angles
        points = np.linspace(min_pt, max_pt, n_angles)
        points += np.random.rand(n_angles) * (max_pt - min_pt) / (5 * n_angles)
        apart = odl.nonuniform_partition(points)
    elif angle == 'nonuniform':
        # Angles spaced quadratically
        min_pt = 2 * (2.0 * np.pi) / n_angles
        max_pt = (2.0 * np.pi) - 2 * (2.0 * np.pi) / n_angles
        points = np.linspace(min_pt ** 0.5, max_pt ** 0.5, n_angles) ** 2
        apart = odl.nonuniform_partition(points)
    else:
        raise ValueError('angle not valid')

    if geom == 'par2d':
        # Discrete reconstruction space
        discr_reco_space = odl.uniform_discr([-20, -20], [20, 20],
                                             [100, 100], dtype=dtype)

        # Geometry
        dpart = odl.uniform_partition(-30, 30, 500)
        geom = tomo.Parallel2dGeometry(apart, dpart)

        # Ray transform
        return tomo.RayTransform(discr_reco_space, geom, impl=impl)

    elif geom == 'par3d':
        # Discrete reconstruction space
        discr_reco_space = odl.uniform_discr([-20, -20, -20], [20, 20, 20],
                                             [100, 100, 100], dtype=dtype)

        # Geometry
        dpart = odl.uniform_partition([-30, -30], [30, 30], [200, 200])
        geom = tomo.Parallel3dAxisGeometry(apart, dpart, axis=[1, 1, 0])

        # Ray transform
        return tomo.RayTransform(discr_reco_space, geom, impl=impl)

    elif geom == 'cone2d':
        # Discrete reconstruction space
        discr_reco_space = odl.uniform_discr([-20, -20], [20, 20],
                                             [100, 100], dtype=dtype)

        # Geometry
        dpart = odl.uniform_partition(-40, 40, 200)
        geom = tomo.FanFlatGeometry(apart, dpart,
                                    src_radius=100, det_radius=100)

        # Ray transform
        return tomo.RayTransform(discr_reco_space, geom, impl=impl)

    elif geom == 'cone3d':
        # Discrete reconstruction space
        discr_reco_space = odl.uniform_discr([-20, -20, -20], [20, 20, 20],
                                             [100, 100, 100], dtype=dtype)

        # Geometry
        dpart = odl.uniform_partition([-50, -50], [50, 50], [200, 200])
        geom = tomo.CircularConeFlatGeometry(
            apart, dpart, src_radius=100, det_radius=100, axis=[1, 0, 0])

        # Ray transform
        return tomo.RayTransform(discr_reco_space, geom, impl=impl)

    elif geom == 'helical':
        # Discrete reconstruction space
        discr_reco_space = odl.uniform_discr([-20, -20, 0], [20, 20, 40],
                                             [100, 100, 100], dtype=dtype)

        # Geometry
        # TODO: angles
        n_angle = 2000
        apart = odl.uniform_partition(0, 8 * 2 * np.pi, n_angle)
        dpart = odl.uniform_partition([-50, -4], [50, 4], [200, 20])
        geom = tomo.HelicalConeFlatGeometry(apart, dpart, pitch=5.0,
                                            src_radius=100, det_radius=100)

        # Windowed ray transform
        return tomo.RayTransform(discr_reco_space, geom, impl=impl)
    else:
        raise ValueError('param not valid')


@skip_if_no_largescale
def test_fbp_reconstruction(projector):
    """Test filtered back-projection with various projectors."""

    # Create Shepp-Logan phantom
    vol = odl.phantom.shepp_logan(projector.domain, modified=False)

    # Project data
    projections = projector(vol)

    # Create default FBP operator and apply to projections
    fbp_operator = odl.tomo.fbp_op(projector)

    # Add window if problem is in 3d.
    if (isinstance(projector.geometry, odl.tomo.HelicalConeFlatGeometry) and
            projector.geometry.pitch != 0):
        fbp_operator = fbp_operator * odl.tomo.tam_danielson_window(projector)

    # Compute the FBP result
    fbp_result = fbp_operator(projections)

    maxerr = vol.norm() / 5.0
    error = vol.dist(fbp_result)
    assert error < maxerr


@skip_if_no_astra_cuda
@skip_if_no_largescale
def test_fbp_reconstruction_filters(filter_type, frequency_scaling):
    """Validate that the various filters work as expected."""

    apart = odl.uniform_partition(0, np.pi, 500)

    discr_reco_space = odl.uniform_discr([-20, -20], [20, 20],
                                         [100, 100], dtype='float32')

    # Geometry
    dpart = odl.uniform_partition(-30, 30, 500)
    geom = tomo.Parallel2dGeometry(apart, dpart)

    # Ray transform
    projector = tomo.RayTransform(discr_reco_space, geom, impl='astra_cuda')

    # Create Shepp-Logan phantom
    vol = odl.phantom.shepp_logan(projector.domain, modified=False)

    # Project data
    projections = projector(vol)

    # Create FBP operator with filters and apply to projections
    fbp_operator = odl.tomo.fbp_op(projector,
                                   filter_type=filter_type,
                                   frequency_scaling=frequency_scaling)

    fbp_result = fbp_operator(projections)

    maxerr = vol.norm() / 5.0
    error = vol.dist(fbp_result)
    assert error < maxerr


if __name__ == '__main__':
    pytest.main([str(__file__.replace('\\', '/')), '-v', '--largescale'])
