import tkinter as tk
import math
from PIL import Image, ImageTk

class RealColorWheel(tk.Canvas):
    
    
    def __init__(self, master, radius=80, callback=None, **kwargs):
        size = radius * 2 + 10
        super().__init__(master, width=size, height=size, **kwargs)
        self.radius = radius
        self.callback = callback
        self._draw_wheel()
        self.bind("<Button-1>", self._click)
        self.cursor = self.create_oval(radius, radius, radius+1, radius+1, outline="white", width=3)
        self.last_hue = 0
        self.last_sat = 1
        
    def set_color(self, h, s, v=1.0):
        # Calcula la posición del cursor en el círculo cromático
        import math
        x = self.radius * s * math.cos(math.radians(h))
        y = self.radius * s * math.sin(math.radians(h))
        cx = int(round(x + self.radius + 5))
        cy = int(round(y + self.radius + 5))
        self.coords(self.cursor, cx-7, cy-7, cx+7, cy+7)
        self.last_hue = h
        self.last_sat = s   

    def _draw_wheel(self):
        img = Image.new("RGB", (self.radius*2+1, self.radius*2+1), (0,0,0))
        for x in range(self.radius*2+1):
            for y in range(self.radius*2+1):
                dx = x - self.radius
                dy = y - self.radius
                r = math.hypot(dx, dy)
                if r <= self.radius:
                    h = (math.degrees(math.atan2(dy, dx)) + 360) % 360
                    s = min(1.0, r / self.radius)
                    v = 1.0
                    rgb = hsv_to_rgb(h, s, v)
                    img.putpixel((x, y), rgb)
        self.imgtk = ImageTk.PhotoImage(img)
        self.create_image(5, 5, anchor="nw", image=self.imgtk)

    def _click(self, event):
        # Mapea el click para que siempre esté dentro del radio
        x = event.x - self.radius - 5
        y = event.y - self.radius - 5
        r = math.hypot(x, y)
        if r > self.radius:
            x = x * self.radius / r
            y = y * self.radius / r
            r = self.radius
        h = (math.degrees(math.atan2(y, x)) + 360) % 360
        s = min(1.0, r / self.radius)
        v = 1.0
        # Snap perfecto si estás muy cerca de los primarios (rojo, verde, azul)
        snap_tolerance = 6  # píxeles
        primaries = [
            (self.radius, 0, 0),         # rojo
            (-self.radius/2, self.radius*math.sqrt(3)/2, 120),  # verde
            (-self.radius/2, -self.radius*math.sqrt(3)/2, 240), # azul
        ]
        for px, py, h_snap in primaries:
            if abs(x - px) < snap_tolerance and abs(y - py) < snap_tolerance:
                h = h_snap
                s = 1.0
        cx = int(round(x + self.radius + 5))
        cy = int(round(y + self.radius + 5))
        self.coords(self.cursor, cx-7, cy-7, cx+7, cy+7)
        self.last_hue = h
        self.last_sat = s
        if self.callback:
            self.callback(h, s, v)
            
            
    def set_color(self, h, s, v=1.0):
        """Posiciona el cursor del wheel según H,S y guarda last_hue/last_sat.
        v se ignora en el dibujo (el wheel siempre es V=1), pero lo aceptamos por compatibilidad.
        """
        import math
        # Normaliza
        h = float(h) % 360
        s = max(0.0, min(1.0, float(s)))
        # Ángulo en radianes
        rad = math.radians(h)
        r = s * self.radius
        x = r * math.cos(rad)
        y = r * math.sin(rad)
        cx = int(round(x + self.radius + 5))
        cy = int(round(y + self.radius + 5))
        self.coords(self.cursor, cx-7, cy-7, cx+7, cy+7)
        self.last_hue = h
        self.last_sat = s
        # No llamamos callback para no disparar envíos de red al sólo visualizar escena            
            

def hsv_to_rgb(h, s, v):
    import colorsys
    r, g, b = colorsys.hsv_to_rgb(h/360.0, s, v)
    return (int(round(r*255)), int(round(g*255)), int(round(b*255)))
