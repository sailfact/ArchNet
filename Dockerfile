FROM archlinux:latest

COPY packages.txt /tmp/packages.txt
COPY entrypoint.sh /usr/local/bin/entrypoint.sh

RUN pacman -Sy --noconfirm archlinux-keyring && \
    pacman -Syu --needed --noconfirm iproute2 && \
    grep -vE '^[[:space:]]*(#|$)' /tmp/packages.txt | \
        pacman -S --needed --noconfirm - && \
    pacman -Scc --noconfirm && \
    chmod +x /usr/local/bin/entrypoint.sh && \
    rm -f /tmp/packages.txt

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["sleep", "infinity"]