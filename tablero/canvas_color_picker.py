import tkinter as tk
import math

class ColorPicker(tk.Canvas):
    """Canvas-based color picker (color wheel) for Tkinter."""

    def __init__(self, master, width=200, height=200, command=None, **kwargs):
        super().__init__(master, width=width, height=height, **kwargs)
        self.width = width
        self.height = height
        self.radius = min(width, height) // 2 - 10
        self.center = (width // 2, height // 2)
        self.command = command
        self.selected_color = (255, 0, 0)
        self.draw_wheel()
        self.bind("<Button-1>", self.select_color)
        self.cursor = self.create_oval(0, 0, 0, 0, outline="white", width=3)

    def draw_wheel(self):
        """Draw the color wheel."""
        for angle in range(360):
            x = self.center[0] + self.radius * math.cos(math.radians(angle))
            y = self.center[1] + self.radius * math.sin(math.radians(angle))
            r, g, b = hsv_to_rgb(angle, 1, 1)
            color = rgb_to_hex(r, g, b)
            self.create_line(self.center[0], self.center[1], x, y, fill=color)

        # Draw the white circle for the center (value)
        for v in range(100, 0, -10):
            self.create_oval(
                self.center[0] - self.radius * v / 100,
                self.center[1] - self.radius * v / 100,
                self.center[0] + self.radius * v / 100,
                self.center[1] + self.radius * v / 100,
                outline="",
                fill=rgb_to_hex(*hsv_to_rgb(0, 0, v/100))
            )

    def select_color(self, event):
        """Handle click event to select a color."""
        x, y = event.x - self.center[0], event.y - self.center[1]
        distance = math.sqrt(x ** 2 + y ** 2)
        if distance > self.radius:
            return  # Click is outside the wheel

        # Get HSV from position
        h = (math.degrees(math.atan2(y, x)) + 360) % 360
        s = min(distance / self.radius, 1)
        v = 1.0

        r, g, b = hsv_to_rgb(h, s, v)
        self.selected_color = (r, g, b)
        self.update_cursor(event.x, event.y)
        if self.command:
            self.command((r, g, b))

    def update_cursor(self, x, y):
        """Move the selection cursor to (x, y)."""
        r = 8
        self.coords(self.cursor, x - r, y - r, x + r, y + r)

def hsv_to_rgb(h, s, v):
    """Convert HSV (0-360, 0-1, 0-1) to RGB (0-255, 0-255, 0-255)."""
    h = float(h)
    s = float(s)
    v = float(v)
    hi = int(h // 60) % 6
    f = h / 60 - hi
    p = v * (1 - s)
    q = v * (1 - f * s)
    t = v * (1 - (1 - f) * s)
    r, g, b = 0, 0, 0
    if hi == 0:
        r, g, b = v, t, p
    elif hi == 1:
        r, g, b = q, v, p
    elif hi == 2:
        r, g, b = p, v, t
    elif hi == 3:
        r, g, b = p, q, v
    elif hi == 4:
        r, g, b = t, p, v
    elif hi == 5:
        r, g, b = v, p, q
    return int(r * 255), int(g * 255), int(b * 255)

def rgb_to_hex(r, g, b):
    """Convert RGB (0-255, 0-255, 0-255) to hex string."""
    return "#%02x%02x%02x" % (int(r), int(g), int(b))
