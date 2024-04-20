# -*- coding: utf-8 -*-
# Copyright 2016-2024 The pyXem developers
#
# This file is part of pyXem.
#
# pyXem is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# pyXem is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with pyXem.  If not, see <http://www.gnu.org/licenses/>.

from warnings import warn

import hyperspy.api as hs
from hyperspy._signals.lazy import LazySignal
from hyperspy.signal import BaseSignal
import numpy as np
from orix.crystal_map import CrystalMap
from orix.quaternion import Rotation
from transforms3d.euler import mat2euler

from pyxem.utils.indexation_utils import get_nth_best_solution
from pyxem.signals.diffraction_vectors2d import DiffractionVectors2D
from pyxem.utils._signals import _transfer_navigation_axes


def crystal_from_vector_matching(z_matches):
    """Takes vector matching results for a single navigation position and
    returns the best matching phase and orientation with correlation and
    reliability to define a crystallographic map.

    Parameters
    ----------
    z_matches : numpy.ndarray
        Template matching results in an array of shape (m,5) sorted by
        total_error (ascending) within each phase, with entries
        [phase, R, match_rate, ehkls, total_error]

    Returns
    -------
    results_array : numpy.ndarray
        Crystallographic mapping results in an array of shape (3) with entries
        [phase, np.array((z, x, z)), dict(metrics)]

    """
    if z_matches.shape == (1,):  # pragma: no cover
        z_matches = z_matches[0]

    # Create empty array for results.
    results_array = np.empty(3, dtype="object")

    # get best matching phase
    best_match = get_nth_best_solution(
        z_matches, "vector", key="total_error", descending=False
    )
    results_array[0] = best_match.phase_index

    # get best matching orientation Euler angles
    results_array[1] = np.rad2deg(mat2euler(best_match.rotation_matrix, "rzxz"))

    # get vector matching metrics
    metrics = dict()
    metrics["match_rate"] = best_match.match_rate
    metrics["ehkls"] = best_match.error_hkls
    metrics["total_error"] = best_match.total_error

    results_array[2] = metrics

    return results_array


def _get_best_match(z):
    """Returns the match with the highest score for a given navigation pixel

    Parameters
    ----------
    z : numpy.ndarray
        array with shape (5,n_matches), the 5 elements are phase, alpha, beta, gamma, score

    Returns
    -------
    z_best : numpy.ndarray
        array with shape (5,)

    """
    return z[np.argmax(z[:, -1]), :]


def _get_phase_reliability(z):
    """Returns the phase reliability (phase_alpha_best/phase_beta_best) for a given navigation pixel

    Parameters
    ----------
    z : numpy.ndarray
        array with shape (5,n_matches), the 5 elements are phase, alpha, beta, gamma, score

    Returns
    -------
    phase_reliabilty : float
        np.inf if only one phase is avaliable
    """
    best_match = _get_best_match(z)
    phase_best = best_match[0]
    phase_best_score = best_match[4]

    # mask for other phases
    lower_phases = z[z[:, 0] != phase_best]
    # needs a second phase, if none return np.inf
    if lower_phases.size > 0:
        phase_second = _get_best_match(lower_phases)
        phase_second_score = phase_second[4]
    else:
        return np.inf

    return phase_best_score / phase_second_score


def _get_second_best_phase(z):
    """Returns the the second best phase for a given navigation pixel

    Parameters
    ----------
    z : numpy.ndarray
        array with shape (5,n_matches), the 5 elements are phase, alpha, beta, gamma, score

    Returns
    -------
    phase_id : int
        associated with the second best phase
    """
    best_match = _get_best_match(z)
    phase_best = best_match[0]

    # mask for other phases
    lower_phases = z[z[:, 0] != phase_best]

    # needs a second phase, if none return -1
    if lower_phases.size > 0:
        phase_second = _get_best_match(lower_phases)
        return phase_second[4]
    else:
        return -1


class OrientationMap(DiffractionVectors2D):
    """Signal class for orientation maps.  Note that this is a special case where
    for each navigation position, the signal contains the top n best matches in the form
    of a nx4 array with columns [index,correlation, in-plane rotation, mirror(factor)]

    The Simulation is saved in the metadata but can be accessed using the .simulation attribute.

    Parameters
    ----------
    *args
        See :class:`~hyperspy._signals.signal2d.Signal2D`.
    **kwargs
        See :class:`~hyperspy._signals.signal2d.Signal2D`
    """

    _signal_type = "orientation_map"

    def __init__(self):
        super().__init__()
        self._signal_type = "orientation_map"

    @property
    def simulation(self):
        return self.metadata.get_item("simulation")

    @simulation.setter
    def simulation(self, value):
        self.metadata.set_item("simulation", value)

    def to_crystal_map(self):
        """Convert the orientation map to an `orix.CrystalMap` object"""
        pass

    def to_markers(self, n_best: int = 1, annotate=False, **kwargs):
        """Convert the orientation map to a set of markers for plotting.

        Parameters
        ----------
        annotate : bool
            If True, the euler rotation and the correlation will be annotated on the plot using
            the `Texts` class from hyperspy.
        """
        def marker_generator_factory(n_best_entry: int):
            def marker_generator(entry):
                # Get data
                index, correlation, rotation, factor = entry[n_best_entry]
                # Get coordinates of reflections
                _, _, coords = self.simulation.get_simulation(int(index))
                # Mirror data if necessary
                coords.data[:, 1] *= factor
                # Rotation matrix for the in-plane rotation
                T = Rotation.from_euler((rotation, 0, 0), degrees=True).to_matrix().squeeze()
                coords = coords.data @ T
                # x and y needs to swap, and we don't want z. Therefore, use slice(1, 0, -1)
                return coords[:, 1::-1]
            return marker_generator

        def reciprocal_lattice_vector_to_text(vec):
            def add_bar(i: int) -> str:
                if i < 0:
                    return f"$\\bar{{{abs(i)}}}$"
                else:
                    return f"{i}"
            out = []
            for hkl in vec.hkl:
                hkl = np.round(hkl).astype(np.int16)
                out.append(f"({add_bar(hkl[0])} {add_bar(hkl[1])} {add_bar(hkl[2])})")
            return out

        def text_generator_factory(n_best_entry: int):
            def text_generator(entry):
                # Get data
                index, correlation, rotation, factor = entry[n_best_entry]
                _, _, vecs = self.simulation.get_simulation(int(index))
                return reciprocal_lattice_vector_to_text(vecs)
            return text_generator

        for n in range(n_best):
            markers_signal = self.map(
                marker_generator_factory(n),
                inplace=False,
                ragged=True,
                lazy_output=True,
            )
            markers = hs.plot.markers.Points.from_signal(markers_signal, color="red")
            yield markers
            if annotate:
                text_signal = self.map(
                    text_generator_factory(n),
                    inplace=False,
                    ragged=True,
                    lazy_output=False,
                )
                texts = np.empty(self.axes_manager.navigation_shape, dtype=object)
                for i in range(texts.shape[0]):
                    for j in range(texts.shape[1]):
                        texts[i, j] = ["a", str(i) + str(j), "a b c"]
                text_markers = hs.plot.markers.Texts.from_signal(markers_signal, texts=np.swapaxes(text_signal.data, 0, 1), color="black")
                yield text_markers


    def to_polar_markers(self, n_best: int = 1):
        r_templates, theta_templates, intensities_templates = self.simulation.polar_flatten_simulations()

        def marker_generator_factory(n_best_entry: int):
            def marker_generator(entry):
                index, correlation, rotation, factor = entry[n_best_entry]
                r = r_templates[int(index)]
                theta = theta_templates[int(index)]
                theta +=  2*np.pi + np.deg2rad(rotation)
                theta %= 2*np.pi
                theta -= np.pi
                return np.array((theta, r)).T
            return marker_generator

        for n in range(n_best):
            markers_signal = self.map(
                marker_generator_factory(n),
                inplace=False,
                ragged=True,
                lazy_output=True,
            )
            markers = hs.plot.markers.Points.from_signal(markers_signal)
            yield markers

    def to_navigator(self):
        """Create a colored navigator and a legend (in the form of a marker) which can be passed as the
        navigator argument to the `plot` method of some signal.
        """
        pass

    def plot_over_signal(self, signal, annotate=False, **kwargs):
        """Convenience method to plot the orientation map and the n-best matches over the signal.

        Parameters
        ----------
        signal : BaseSignal
            The signal to plot the orientation map over.
        annotate: bool
            If True, the euler rotation and the correlation will be annotated on the plot using
            the `Texts` class from hyperspy.

        """
        pass

    def plot_inplane_rotation(self, **kwargs):
        """Plot the in-plane rotation of the orientation map as a 2D map."""
        pass


class GenericMatchingResults:
    def __init__(self, data):
        self.data = hs.signals.Signal2D(data)

    def to_crystal_map(self):
        """
        Exports an indexation result with multiple results per navigation position to
        crystal map with one result per pixel

        Returns
        -------
        :class:`~orix.crystal_map.CrystalMap`

        """
        _s = self.data.map(_get_best_match, inplace=False)

        """ Gets properties """
        phase_id = _s.isig[0].data.flatten()
        alpha = _s.isig[1].data.flatten()
        beta = _s.isig[2].data.flatten()
        gamma = _s.isig[3].data.flatten()
        score = _s.isig[4].data.flatten()

        """ Gets navigation placements """
        xy = np.indices(_s.data.shape[:2])
        x = xy[1].flatten()
        y = xy[0].flatten()

        """ Tidies up so we can put these things into CrystalMap """
        euler = np.deg2rad(np.vstack((alpha, beta, gamma)).T)
        rotations = Rotation.from_euler(
            euler, convention="bunge", direction="crystal2lab"
        )

        """ add various properties """
        phase_reliabilty = self.data.map(
            _get_phase_reliability, inplace=False
        ).data.flatten()
        second_phase = self.data.map(
            _get_second_best_phase, inplace=False
        ).data.flatten()
        properties = {
            "score": score,
            "phase_reliabilty": phase_reliabilty,
            "second_phase": second_phase,
        }

        return CrystalMap(
            rotations=rotations, phase_id=phase_id, x=x, y=y, prop=properties
        )


class LazyOrientationMap(LazySignal, OrientationMap):
    pass


class VectorMatchingResults(BaseSignal):
    """Vector matching results containing the top n best matching crystal
    phase and orientation at each navigation position with associated metrics.

    Attributes
    ----------
    vectors : pyxem.signals.DiffractionVectors
        Diffraction vectors indexed.
    hkls : BaseSignal
        Miller indices associated with each diffraction vector.
    """

    _signal_dimension = 0
    _signal_type = "vector_matching"

    def __init__(self, *args, **kwargs):
        BaseSignal.__init__(self, *args, **kwargs)
        # self.axes_manager.set_signal_dimension(2)
        self.vectors = None
        self.hkls = None

    def get_crystallographic_map(self, *args, **kwargs):
        """Obtain a crystallographic map specifying the best matching phase and
        orientation at each probe position with corresponding metrics.

        Returns
        -------
        cryst_map : Signal2D
            Crystallographic mapping results containing the best matching phase
            and orientation at each navigation position with associated metrics.
            The Signal at each navigation position is an array of,
            [phase, np.array((z,x,z)), dict(metrics)]
            which defines the phase, orientation as Euler angles in the zxz
            convention and metrics associated with the matching.
            Metrics for template matching results are
            'match_rate'
            'total_error'
            'orientation_reliability'
            'phase_reliability'
        """
        crystal_map = self.map(
            crystal_from_vector_matching, inplace=False, *args, **kwargs
        )

        crystal_map = _transfer_navigation_axes(crystal_map, self)
        return crystal_map

    def get_indexed_diffraction_vectors(
        self, vectors, overwrite=False, *args, **kwargs
    ):
        """Obtain an indexed diffraction vectors object.

        Parameters
        ----------
        vectors : pyxem.signals.DiffractionVectors
            A diffraction vectors object to be indexed.

        Returns
        -------
        indexed_vectors : pyxem.signals.DiffractionVectors
            An indexed diffraction vectors object.

        """
        if overwrite is False:
            if vectors.hkls is not None:
                warn(
                    "The vectors supplied are already associated with hkls set "
                    "overwrite=True to replace these hkls."
                )
            else:
                vectors.hkls = self.hkls

        elif overwrite is True:
            vectors.hkls = self.hkls

        return vectors
