import tkinter as tk
from PIL import Image, ImageTk
import math

class ColorBarPicker(tk.Canvas):
    def __init__(self, master, width=280, height=80, callback=None, **kwargs):
        super().__init__(master, width=width, height=height, **kwargs)
        self.width = width
        self.height = height
        self.callback = callback
        self._draw_bar()
        self.bind("<Button-1>", self._click)
        self.cursor = self.create_oval(0,0,0,0,outline="white",width=3)

    def _draw_bar(self):
        img = Image.new("RGB", (self.width, self.height))
        for x in range(self.width):
            h = (x / (self.width - 1)) * 360
            for y in range(self.height):
                # s = 1 - (y / (height-1)): saturación va de 1 (arriba) a 0 (abajo)
                # v = 1 siempre: color puro
                s = 1 - (y / (self.height - 1))
                v = 1
                r,g,b = hsv_to_rgb(h, s, v)
                img.putpixel((x, y), (r, g, b))
        self.imgtk = ImageTk.PhotoImage(img)
        self.create_image(0,0,anchor="nw",image=self.imgtk)

    def _click(self, event):
        x = min(max(event.x, 0), self.width-1)
        y = min(max(event.y, 0), self.height-1)
        h = (x / (self.width - 1)) * 360
        s = 1 - (y / (self.height - 1))
        v = 1
        r = 8
        self.coords(self.cursor, x-r, y-r, x+r, y+r)
        if self.callback:
            self.callback(h, s, v)

def hsv_to_rgb(h, s, v):
    import colorsys
    r,g,b = colorsys.hsv_to_rgb(h/360.0, s, v)
    return int(r*255), int(g*255), int(b*255)


