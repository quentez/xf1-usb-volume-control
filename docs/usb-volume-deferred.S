# XF1 20D38E18: replacement for file 0xc830..0xc862 (XIP 0x1000c830).
# Preserve the USB echo-suppression flag, last-level cache and global level.
# Tail-call the same event-post entry used by Bluetooth with event 0x7f2.
# tp is initialized to 0x84800 by the existing application entry point.
# This is an experimental scheduling change, with no gain ramp.
# Assemble with upstream Clang built with RISC-V support (not Apple's Clang):
# clang -target riscv32-unknown-elf -march=rv32imc -mabi=ilp32 \
#   -c docs/usb-volume-deferred.S -o /tmp/xf1-usb-volume-deferred.o

.option rvc
.option norelax
.text
.global usb_volume_deferred
usb_volume_deferred:
    c.lui a3, 0x18
    lbu a2, -0x1d3(a3)
    c.beqz a2, changed_check
    c.li a4, -1
    sb a4, -0x1d4(a3)
    sb zero, -0x1d3(a3)
    c.jr ra
changed_check:
    lbu a4, -0x1d4(a3)
    beq a4, a0, unchanged
    sb a0, -0x1d4(a3)
    lui a4, 0x50
    sb a0, -0x46f(a4)
    addi a0, zero, 0x7f2
    jalr zero, tp, -0x74c
unchanged:
    c.jr ra
