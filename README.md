# Making Arch accessible to anyone <3

## PacToPac 
Simple GUI for pacman/flatpak using Subprocess.

![Screenshot_20250524_173817](https://github.com/user-attachments/assets/377cad96-f707-497a-9729-c949c9626663)
![Screenshot_20250524_173736](https://github.com/user-attachments/assets/cc7f8380-d3e3-4b0a-bf26-38a0011f74f8)

---

### Get it running:
```
$ pacman -S python-gobject gtk4 libadwaita
$ sudo python3 main.py
``` 

#### What?

**Settings:**
> Settings was the most important part for me in this project because they correct things you'd have to do manually.

- Enable multi-lib
- Mirrors
- Detect Hardware
- Flatpak

**Core features:**

- Subprocess display
- Package info/install/remove/clean
- Search
