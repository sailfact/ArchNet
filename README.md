# README

## Build Tools
```sh
pacman -Syu --noconfirm
pacman -S archiso --noconfirm
```
## Build ISO
```sh
cd /workspace/profile
mkarchiso -v -w /tmp/archiso-tmp -o /workspace/_out/ .
```