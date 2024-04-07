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


import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.axes_grid1.anchored_artists import AnchoredSizeBar
from scipy.ndimage import rotate, gaussian_filter
import pyxem.utils._pixelated_stem_tools as pst
from hyperspy._signals.lazy import LazySignal
from hyperspy.signals import BaseSignal, Signal1D, Signal2D


def make_bivariate_histogram(
    x_position, y_position, histogram_range=None, masked=None, bins=200, spatial_std=3
):
    s0_flat = x_position.flatten()
    s1_flat = y_position.flatten()

    if masked is not None:
        temp_s0_flat = []
        temp_s1_flat = []
        for data0, data1, masked_value in zip(s0_flat, s1_flat, masked.flatten()):
            if not masked_value:
                temp_s0_flat.append(data0)
                temp_s1_flat.append(data1)
        s0_flat = np.array(temp_s0_flat)
        s1_flat = np.array(temp_s1_flat)

    if histogram_range is None:
        if s0_flat.std() > s1_flat.std():
            s0_range = (
                s0_flat.mean() - s0_flat.std() * spatial_std,
                s0_flat.mean() + s0_flat.std() * spatial_std,
            )
            s1_range = (
                s1_flat.mean() - s0_flat.std() * spatial_std,
                s1_flat.mean() + s0_flat.std() * spatial_std,
            )
        else:
            s0_range = (
                s0_flat.mean() - s1_flat.std() * spatial_std,
                s0_flat.mean() + s1_flat.std() * spatial_std,
            )
            s1_range = (
                s1_flat.mean() - s1_flat.std() * spatial_std,
                s1_flat.mean() + s1_flat.std() * spatial_std,
            )
    else:
        s0_range = histogram_range
        s1_range = histogram_range

    hist2d, xedges, yedges = np.histogram2d(
        s0_flat,
        s1_flat,
        bins=bins,
        range=[[s0_range[0], s0_range[1]], [s1_range[0], s1_range[1]]],
    )

    s_hist = Signal2D(hist2d).swap_axes(0, 1)
    s_hist.axes_manager[0].offset = xedges[0]
    s_hist.axes_manager[0].scale = xedges[1] - xedges[0]
    s_hist.axes_manager[1].offset = yedges[0]
    s_hist.axes_manager[1].scale = yedges[1] - yedges[0]
    return s_hist


def _get_corner_mask(s, corner_size=0.05):
    corner_slice_list = pst._get_corner_slices(
        s, corner_size=corner_size,
    )
    mask = np.ones_like(s.data, dtype=bool)
    for corner_slice in corner_slice_list:
        mask[corner_slice] = False

    s_mask = s._deepcopy_with_new_data(mask).T
    return s_mask


class BeamShift(Signal1D):
    """Signal class for working with shift of the direct beam."""

    _signal_type = "beam_shift"

    def get_linear_plane(self, mask=None, fit_corners=None):
        """Fit linear planes to the beam shifts, which replaces the original data.

        In many scanning transmission electron microscopes, the center position of the
        diffraction pattern will change as a function of the scan position. This is most
        apparent when scanning over large regions (100+ nanometers). Thus, when working
        with datasets, it is typically necessary to correct for this.
        However, other effects can also affect the apparent center point, like
        diffraction contrast. So while it is possible to correct for the beam shift
        by finding the center position in each diffraction pattern, this can lead to
        features such as interfaces or grain boundaries affecting the centering of the
        diffraction pattern. As the shift caused by the scan system is a slow and
        monotonic, it can often be approximated by fitting linear planes to
        the x- and y- beam shifts.

        In addition, for regions within the scan where the center point of the direct
        beam is hard to ascertain precisely, for example in very thick or heavily
        diffracting regions, a mask can be used to ignore fitting the plane to
        these regions.

        This method does this, and replaces the original beam shift data with these
        fitted planes. The beam shift signal can then be directly used in the
        :meth:`~pyxem.signals.Diffraction2D.center_direct_beam` method.

        Note that for very large regions, this linear plane will probably not
        approximate the beam shift very well. In those cases a higher order plane
        will likely be necessary. Alternatively, a vacuum scan with exactly the same
        scanning parameters should be used.

        Parameters
        ----------
        mask : HyperSpy signal, optional
            Must be the same shape as the navigation dimensions of the beam
            shift signal. The True values will be masked.
        fit_corners : float, optional
            Make a mask so that the planes are fitted to the corners of the
            signal. This mush be set with a number, like 0.05 (5%) or 0.10 (10%).

        Examples
        --------
        >>> s = pxm.signals.BeamShift(np.random.randint(0, 99, (100, 120, 2)))
        >>> s_mask = hs.signals.Signal2D(np.zeros((100, 120), dtype=bool))
        >>> s_mask.data[20:-20, 20:-20] = True
        >>> s.make_linear_plane(mask=s_mask)

        """
        if self._lazy:
            raise ValueError(
                "make_linear_plane is not implemented for lazy signals, "
                "run compute() first"
            )
        if (mask is not None) and (fit_corners is not None):
            raise ValueError("Only mask or fit_to_corners can be set.")
        if fit_corners is not None:
            mask = _get_corner_mask(self.isig[0], corner_size=fit_corners)

        s_shift_x = self.isig[0].T
        s_shift_y = self.isig[1].T
        if mask is not None:
            mask = mask.__array__()
        plane_image_x = pst._get_linear_plane_from_signal2d(s_shift_x, mask=mask)
        plane_image_y = pst._get_linear_plane_from_signal2d(s_shift_y, mask=mask)
        plane_image = np.stack((plane_image_x, plane_image_y), -1)
        s_bs = self._deepcopy_with_new_data(plane_image)
        return s_bs

    def plot(self):
        self.T.plot()

    def get_bivariate_histogram(
        self, histogram_range=None, masked=None, bins=200, spatial_std=3
    ):
        """
        Useful for finding the distribution of magnetic vectors(?).

        Parameters
        ----------
        histogram_range : tuple, optional
            Set the minimum and maximum of the histogram range.
            Default is setting it automatically.
        masked : 2-D NumPy bool array, optional
            Mask parts of the data. The array must be the same
            size as the signal. The True values are masked.
            Default is not masking anything.
        bins : integer, default 200
            Number of bins in the histogram
        spatial_std : number, optional
            If histogram_range is not given, this value will be
            used to set the automatic histogram range.
            Default value is 3.

        Returns
        -------
        s_hist : HyperSpy Signal2D

        Examples
        --------
        >>> s = pxm.dummy_data.get_stripe_pattern_dpc_signal()
        >>> s_hist = s.get_bivariate_histogram()
        >>> s_hist.plot()

        """
        x_position = self.isig[0].data
        y_position = self.isig[1].data
        s_hist = make_bivariate_histogram(
            x_position,
            y_position,
            histogram_range=histogram_range,
            masked=masked,
            bins=bins,
            spatial_std=spatial_std,
        )
        s_hist.metadata.General.title = "Bivariate histogram of {0}".format(
            self.metadata.General.title
        )
        return s_hist

    def get_magnitude_signal(
        self, autolim=True, autolim_sigma=4, magnitude_limits=None
    ):
        """Get DPC magnitude image visualized as greyscale.

        Converts the x and y beam shifts into a magnitude map, showing the
        magnitude of the beam shifts.

        Useful for visualizing magnetic domain structures.

        Parameters
        ----------
        autolim : bool, default True
        autolim_sigma : float, default 4
        magnitude_limits : tuple of floats, default None
            Manually sets the value limits for the magnitude signal.
            For this, autolim needs to be False.

        Returns
        -------
        magnitude_signal : HyperSpy 2D signal

        Examples
        --------
        >>> s = pxm.dummy_data.get_simple_dpc_signal()
        >>> s_magnitude = s.get_magnitude_signal()
        >>> s_magnitude.plot()

        See Also
        --------
        get_color_signal : Signal showing both phase and magnitude
        get_phase_signal : Signal showing the phase

        """
        def magnitude_calc_with_map(image):
            x, y = image
            mag = np.hypot(x, y)
            return mag

        s_magnitude = self.map(magnitude_calc_with_map, inplace=False)
        s_magnitude = s_magnitude.T


        if autolim:
            if magnitude_limits is not None:
                raise ValueError(
                    "If autolim==True then `magnitude_limits` must be set to None"
                )

            magnitude_limits = pst._get_limits_from_array(
                s_magnitude.data, sigma=autolim_sigma
            )
        if magnitude_limits is not None:
            np.clip(
                s_magnitude.data,
                magnitude_limits[0],
                magnitude_limits[1],
                out=s_magnitude.data,
            )

        s_magnitude.metadata.General.title = "Magnitude of {0}".format(
            self.metadata.General.title
        )
        return s_magnitude

    def phase_retrieval(self, method="kottler", mirroring=False, mirror_flip=False):
        """Retrieve the phase from two orthogonal phase gradients.

        Parameters
        ----------
        method : 'kottler', 'arnison' or 'frankot', optional
            the formula to use, kottler [1]_ , arnison [2]_ and frankot [3]_
            are available. The default is 'kottler'.
        mirroring : bool, optional
            whether to mirror the phase gradients before Fourier transformed.
            Attempt to reduce boundary effect. The default is False.
        mirror_flip : bool, optional
            only active when 'mirroring' is True. Flip the direction of the
            derivatives which results in negation during signal mirroring.
            The default is False. If the retrieved phase is not sensible after
            mirroring, set this to True may resolve it.

        Raises
        ------
        ValueError
            If the method is not implemented

        Returns
        -------
        signal : HyperSpy 2D signal
            the phase retrieved.

        References
        ----------
        .. [1] Kottler, C., David, C., Pfeiffer, F. and Bunk, O., 2007. A
           two-directional approach for grating based differential phase contrast
           imaging using hard x-rays. Optics Express, 15(3), p.1175. (Equation 4)

        .. [2] Arnison, M., Larkin, K., Sheppard, C., Smith, N. and
           Cogswell, C., 2004. Linear phase imaging using differential
           interference contrast microscopy. Journal of Microscopy, 214(1),
           pp.7-12. (Equation 6)

        .. [3] Frankot, R. and Chellappa, R., 1988. A method for enforcing
           integrability in shape from shading algorithms.
           IEEE Transactions on Pattern Analysis and Machine Intelligence,
           10(4), pp.439-451. (Equation 21)

        Examples
        --------
        >>> s = pxm.dummy_data.get_square_dpc_signal()
        >>> s_phase = s.phase_retrieval()
        >>> s_phase.plot()

        """

        method = method.lower()
        if method not in ("kottler", "arnison", "frankot"):
            raise ValueError(
                "Method '{}' not recognised. 'kottler', 'arnison'"
                " and 'frankot' are available.".format(method)
            )

        # get x and y phase gradient
        dx = self.isig[0].data
        dy = self.isig[1].data

        # attempt to reduce boundary effect
        if mirroring:
            Ax = dx
            Bx = np.flip(dx, axis=1)
            Cx = np.flip(dx, axis=0)
            Dx = np.flip(dx)

            Ay = dy
            By = np.flip(dy, axis=1)
            Cy = np.flip(dy, axis=0)
            Dy = np.flip(dy)

            # the -ve depends on the direction of derivatives
            if not mirror_flip:
                dx = np.bmat([[Ax, -Bx], [Cx, -Dx]]).A
                dy = np.bmat([[Ay, By], [-Cy, -Dy]]).A
            else:
                dx = np.bmat([[Ax, Bx], [-Cx, -Dx]]).A
                dy = np.bmat([[Ay, -By], [Cy, -Dy]]).A

        nc, nr = dx.shape[1], dx.shape[0]

        # get scan step size
        calX = np.diff(self.axes_manager.navigation_axes[0].axis).mean()
        calY = np.diff(self.axes_manager.navigation_axes[1].axis).mean()

        # construct Fourier-space grids
        kx = (2 * np.pi) * np.fft.fftshift(np.fft.fftfreq(nc))
        ky = (2 * np.pi) * np.fft.fftshift(np.fft.fftfreq(nr))
        kx_grid, ky_grid = np.meshgrid(kx, ky)

        if method == "kottler":
            gxy = dx + 1j * dy
            numerator = np.fft.fftshift(np.fft.fft2(gxy))
            denominator = 2 * np.pi * 1j * (kx_grid + 1j * ky_grid)
        elif method == "arnison":
            gxy = dx + 1j * dy
            numerator = np.fft.fftshift(np.fft.fft2(gxy))
            denominator = 2j * (
                np.sin(2 * np.pi * calX * kx_grid)
                + 1j * np.sin(2 * np.pi * calY * ky_grid)
            )
        elif method == "frankot":
            kx_grid /= calX
            ky_grid /= calY
            fx = np.fft.fftshift(np.fft.fft2(dx))
            fy = np.fft.fftshift(np.fft.fft2(dy))
            # weights in x,y directins, currently hardcoded, but easy to extend if required
            wx, wy = 0.5, 0.5

            numerator = -1j * (wx * kx_grid * fx + wy * ky_grid * fy)
            denominator = wx * kx_grid**2 + wy * ky_grid**2

        # handle the division by zero in the central pixel
        # set the undefined/infinity pixel to 0
        with np.errstate(divide="ignore", invalid="ignore"):
            res = numerator / denominator
        res = np.nan_to_num(res, nan=0, posinf=0, neginf=0)

        retrieved = np.fft.ifft2(np.fft.ifftshift(res)).real

        # get 1/4 of the result if mirroring
        if mirroring:
            M, N = retrieved.shape
            retrieved = retrieved[: M // 2, : N // 2]

        signal = self._deepcopy_with_new_data(retrieved)
        signal._remove_axis(-1)
        signal = signal.T
        signal.metadata.General.title = "Phase retrieval of {0}".format(
            self.metadata.General.title
        )
        return signal

    def get_phase_signal(self, rotation=None):
        """Get DPC phase image visualized using continuous color scale.

        Converts the x and y beam shifts into an RGB array, showing the
        direction of the beam shifts.

        Useful for visualizing magnetic domain structures.

        Parameters
        ----------
        rotation : float, optional
            In degrees. Useful for correcting the mismatch between
            scan direction and diffraction pattern rotation.
        autolim : bool, default True
        autolim_sigma : float, default 4

        Returns
        -------
        phase_signal : HyperSpy 2D RGB signal

        Examples
        --------
        >>> s = pxm.dummy_data.get_simple_dpc_signal()
        >>> s_color = s.get_phase_signal(rotation=20)
        >>> s_color.plot()

        See Also
        --------
        get_color_signal : Signal showing both phase and magnitude
        get_magnitude_signal : Signal showing the magnitude

        """

        if self.axes_manager.navigation_dimension != 2:
            raise ValueError(
                "get_phase_signal only works with 2 navigation dimensions"
            )
        # Rotate the phase by -30 degrees in the color "wheel", to get better
        # visualization in the vertical and horizontal direction.
        rotation = None
        if rotation is None:
            rotation = -30
        else:
            rotation = rotation - 30

        phase = np.arctan2(self.isig[0].data, self.isig[1].data) % (2 * np.pi)
        rgb_array = pst._get_rgb_phase_array(phase=phase, rotation=rotation)
        rgb_array_16bit = rgb_array * (2**16 - 1)
        s_rgb = self._deepcopy_with_new_data(rgb_array_16bit)
        s_rgb.change_dtype("uint16")
        s_rgb.change_dtype("rgb16")
        return s_rgb

    def get_color_signal(
        self, rotation=None, autolim=True, autolim_sigma=4, magnitude_limits=None
    ):
        """Get DPC image visualized using continuous color scale.

        Converts the x and y beam shifts into an RGB array, showing the
        magnitude and direction of the beam shifts.

        Useful for visualizing magnetic domain structures.

        Parameters
        ----------
        rotation : float, optional
            In degrees. Useful for correcting the mismatch between
            scan direction and diffraction pattern rotation.
        autolim : bool, default True
        autolim_sigma : float, default 4
        magnitude_limits : tuple of floats, default None
            Manually sets the value limits for the color signal.
            For this, autolim needs to be False.

        Returns
        -------
        color_signal : HyperSpy 2D RGB signal

        Examples
        --------
        >>> s = pxm.dummy_data.get_simple_dpc_signal()
        >>> s_color = s.get_color_signal()
        >>> s_color.plot()

        Rotate the beam shift by 30 degrees

        >>> s_color = s.get_color_signal(rotation=30)

        See Also
        --------
        get_color_signal : Signal showing both phase and magnitude
        get_phase_signal : Signal showing the phase

        """
        # Rotate the phase by -30 degrees in the color "wheel", to get better
        # visualization in the vertical and horizontal direction.
        if rotation is None:
            rotation = -30
        else:
            rotation = rotation - 30
        phase = np.arctan2(self.isig[0].data, self.isig[1].data) % (2 * np.pi)
        magnitude = np.hypot(self.isig[0].data, self.isig[1].data)

        if autolim:
            if magnitude_limits is not None:
                raise ValueError(
                    "If autolim==True then `magnitude_limits` must be set to None"
                )

            magnitude_limits = pst._get_limits_from_array(
                magnitude, sigma=autolim_sigma
            )
        rgb_array = pst._get_rgb_phase_magnitude_array(
            phase=phase,
            magnitude=magnitude,
            rotation=rotation,
            magnitude_limits=magnitude_limits,
        )
        rgb_array_16bit = rgb_array * (2**16 - 1)
        s_rgb = self._deepcopy_with_new_data(rgb_array_16bit)
        s_rgb.change_dtype("uint16")
        s_rgb.change_dtype("rgb16")
        return s_rgb

    def get_color_image_with_indicator(
        self,
        phase_rotation=0,
        indicator_rotation=0,
        only_phase=False,
        autolim=True,
        autolim_sigma=4,
        magnitude_limits=None,
        scalebar_size=None,
        ax=None,
        ax_indicator=None,
    ):
        """Make a matplotlib figure showing DPC contrast.

        Parameters
        ----------
        phase_rotation : float, default 0
            Changes the phase of the plotted data.
            Useful for correcting scan rotation.
        indicator_rotation : float, default 0
            Changes the color wheel rotation.
        only_phase : bool, default False
            If False, will plot both the magnitude and phase.
            If True, will only plot the phase.
        autolim : bool, default True
        autolim_sigma : float, default 4
        magnitude_limits : tuple of floats, default None
            Manually sets the value limits for the color signal.
            For this, autolim needs to be False.
        scalebar_size : int, optional
        ax : Matplotlib subplot, optional
        ax_indicator : Matplotlib subplot, optional
            If None, generate a new subplot for the indicator.
            If False, do not include an indicator

        Examples
        --------
        >>> s = pxm.dummy_data.get_simple_dpc_signal()
        >>> fig = s.get_color_image_with_indicator()
        >>> fig.savefig("simple_dpc_test_signal.png")

        Only plotting the phase

        >>> fig = s.get_color_image_with_indicator(only_phase=True)
        >>> fig.savefig("simple_dpc_test_signal.png")

        Matplotlib subplot as input

        >>> import matplotlib.pyplot as plt
        >>> fig, ax = plt.subplots()
        >>> ax_indicator = fig.add_subplot(331)
        >>> fig_return = s.get_color_image_with_indicator(
        ...     scalebar_size=10, ax=ax, ax_indicator=ax_indicator)

        """
        indicator_rotation = indicator_rotation + 60
        if ax is None:
            set_fig = True
            fig, ax = plt.subplots(1, 1, figsize=(7, 7))
        else:
            fig = ax.figure
            set_fig = False
        if only_phase:
            s = self.get_phase_signal(rotation=phase_rotation)
        else:
            s = self.get_color_signal(
                rotation=phase_rotation,
                autolim=autolim,
                autolim_sigma=autolim_sigma,
                magnitude_limits=magnitude_limits,
            )
        s.change_dtype("uint16")
        s.change_dtype("float64")
        extent = s.axes_manager.navigation_extent
        extent = [extent[0], extent[1], extent[3], extent[2]]
        ax.imshow(s.data / 65536.0, extent=extent)
        if ax_indicator is not False:
            if ax_indicator is None:
                ax_indicator = fig.add_subplot(331)
            pst._make_color_wheel(
                ax_indicator, rotation=indicator_rotation + phase_rotation
            )
        ax.set_axis_off()
        if scalebar_size is not None:
            scalebar_label = "{0} {1}".format(scalebar_size, s.axes_manager[0].units)
            sb = AnchoredSizeBar(ax.transData, scalebar_size, scalebar_label, loc=4)
            ax.add_artist(sb)
        if set_fig:
            fig.subplots_adjust(0, 0, 1, 1)
        return fig

    def rotate_beam_shifts(self, angle):
        """Rotate the beam shift vector.

        Parameters
        ----------
        angle : float
            Clockwise rotation in degrees

        Returns
        -------
        shift_rotated_signal : DPCSignal2D

        Example
        -------

        Rotate beam shifts by 10 degrees clockwise

        >>> s = pxm.dummy_data.get_simple_dpc_signal()
        >>> s_new = s.rotate_beam_shifts(10)
        >>> s_new.plot()

        """
        angle_rad = np.deg2rad(angle)
        x, y = self.isig[0].data, self.isig[1].data
        x_new = x * np.cos(angle_rad) - y * np.sin(angle_rad)
        y_new = x * np.sin(angle_rad) + y * np.cos(angle_rad)
        s_new = self._deepcopy_with_new_data(np.stack((x_new, y_new), axis=-1))
        return s_new

    def rotate_scan_dimensions(self, angle, reshape=False):
        """Rotate the scan dimensions by angle.

        Parameters
        ----------
        angle : float
            Clockwise rotation in degrees

        Returns
        -------
        rotated_signal : DPCSignal2D

        Example
        -------

        Rotate data by 10 degrees clockwise

        >>> s = pxm.dummy_data.get_simple_dpc_signal()
        >>> s_rot = s.rotate_data(10)
        >>> s_rot.plot()

        """
        s_temp = self.T
        s_temp2 = s_temp.map(
            rotate,
            show_progressbar=False,
            inplace=False,
            reshape=reshape,
            angle=-angle,
        )
        s_new = s_temp2.T
        return s_new


class LazyBeamShift(BeamShift, LazySignal):
    _signal_type = "beam_shift"

    pass
