import time
import matplotlib.pyplot as plt
from matplotlib.widgets import PolygonSelector

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


    def _polygon_update(verts):
        print(verts)
        ax.plot(*list(zip(*verts)),"go")
        fig.canvas.draw()
        fig.canvas.flush_events()
        _polygon_update.verts = verts


    _polygon_update.verts = []

    poly = PolygonSelector(
        ax, onselect= _polygon_update, handle_props=handle_props, props=props
    )

    fig.tight_layout()
    plt.show()

    # xs = [10, 40, 80, 20]
    # ys = [20,50,60,10]
    # class Hold:
    #     pass
    # event = Hold()
    # event.button = 1

    # for x,y in zip(xs,ys):
    #     event.xdata = x
    #     event.ydata = y
    #     poly._release(event)
    return poly
