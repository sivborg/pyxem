import matplotlib.pyplot as plt
from matplotlib.widgets import PolygonSelector
import numpy as np
from PIL import Image, ImageDraw

def mask_from_polygon(reference_image, invert_selection = False):

    fig,ax = plt.subplots(1,figsize=(6,6))
    ax.set_title(
            "Use the left mouse button to make the polygon.\n"
            "Click the first position to finish the polygon.\n"
            "Press ESC to reset the polygon, and hold SHIFT to\n"
            "move the polygon."
        )

    cax = ax.imshow(reference_image)

    handle_props = dict(color="blue")
    props = dict(color="blue")
    mask_vertices = []

    closed_figure = False
    def _on_close(event):
        nonlocal closed_figure
        closed_figure = True
    fig.canvas.mpl_connect('close_event', _on_close)

    def _polygon_update(verts):
        nonlocal mask_vertices
        mask_vertices = verts

    polygon_selector = PolygonSelector(
        ax, onselect= _polygon_update, handle_props=handle_props, props=props
    )

    fig.tight_layout()
    plt.show()

    # This loop is necessary in interactive mode for halting the function until
    # points are selected in the PolygonSelector.
    while not closed_figure:
        plt.pause(1)

    img = Image.new("L",reference_image.shape,0)
    ImageDraw.Draw(img).polygon(mask_vertices,fill=1)
    mask = np.array(img)

    return mask
