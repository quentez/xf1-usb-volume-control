# XF1 20D38E18 USB Audio 1.0 volume feedback.
# Original code is reached through symbols in usb-volume-feedback.ld.
# No audio samples, gain routines, flash routines or Bluetooth state are touched.
#
# Capture is disabled in this product's flags=7 configuration. Reuse its IN3
# context/buffer for two-byte AC status messages, with IN3 interrupts disabled.
# OUT3 audio and IN/OUT1 mass storage remain independent hardware directions.
# Only the existing USB task accesses endpoint registers or feedback state.
# The main USB loop merely posts a coalesced work item to that task.
#
# Capture buffer 0x62448: [0:2] status, [8] dirty, [9] reserved,
# [10] work item queued. Original audio initialization zeroes all 256 bytes.
.option rvc
.option norelax

.section .feedback_core,"ax",@progbits
.global feedback_sync, feedback_notify, feedback_event, feedback_get_volume

# Preserve a0/a1, and all callee-saved registers. Called in the USB task.
# Host SET_CUR already updates both mapped level and global level, so matching
# levels leave its exact 1/256 dB readback intact.
feedback_sync:
    li a2, 0x62018
    lbu a3, 0x3b(a2)
    li a4, 7
    bne a3, a4, 9f
    li a3, 0x4f248
    lbu a3, 0(a3)
    li a4, 6
    bne a3, a4, 9f
    li a3, 0x4fb91
    lbu a3, 0(a3)
    li a4, 32
    bltu a4, a3, 9f
    lbu a5, 0x16(a2)
    bne a5, a4, 9f
    lbu a4, 0xd(a2)
    beq a3, a4, 9f
    lw a4, 0x1c(a2)
    li a5, 0x1000dc5c
    bne a4, a5, 9f
    slli a5, a3, 1
    add a4, a4, a5
    lh a4, 0(a4)
    sh a4, 0xa(a2)
    sb a3, 0xd(a2)
    li a4, 0x17e2c
    sb a3, 0(a4)
    li a4, 1
    sb a4, 0x438(a2)      # 0x62450 dirty
9:  ret

# No waiting for the host. The existing transfer primitive arms one packet;
# if its FIFO is busy, leave dirty set for the next USB-loop work item.
feedback_notify:
    li a5, 0x62018
    lbu a4, 0x3a(a5)      # configuration value, not device address
    li a3, 1
    bne a4, a3, 9f
    lw a4, 0(a5)
    lbu a4, 4(a4)
    li a3, 2
    bne a4, a3, 9f        # must have been configured as status IN3
    lbu a4, 0x438(a5)
    beqz a4, 9f
    addi sp, sp, -16
    sw ra, 12(sp)
    li a4, 0x15b44
    lw a4, 0(a4)
    sw a4, 8(sp)
    # Refresh the fixed message for every transfer. TXPKTRDY in the original
    # primitive prevents reuse until the host has consumed the previous packet.
    # Do not wait for GET_STAT: hosts can reread controls without sending it.
    li a4, 0x280
    sh a4, 0x430(a5)
    lw a0, 0(a5)
    li a1, 2
    jal ra, original_start_transfer
    li a5, 0x62018
    lw a4, 0(a5)
    lhu a4, 0x10(a4)
    bnez a4, 1f          # packet not armed; retry later
    sb zero, 0x438(a5)
1:  lw a0, 8(sp)
    jal ra, original_select_endpoint
    lw ra, 12(sp)
    addi sp, sp, 16
9:  ret

# New event 0x25 in the USB task's existing dispatch table. It was a no-op.
feedback_event:
    li a5, 0x62450
    sb zero, 2(a5)
    jal ra, feedback_sync
    jal ra, feedback_notify
    lui a5, %hi(original_usb_task_loop)
    addi a5, a5, %lo(original_usb_task_loop)
    jr a5

feedback_get_volume:
    li a5, 0x81
    bne a0, a5, 1f
    addi sp, sp, -16
    sw ra, 12(sp)
    jal ra, feedback_sync
    lw ra, 12(sp)
    addi sp, sp, 16
1:  j original_get_volume

.section .feedback_setup,"ax",@progbits
.global feedback_descriptor, feedback_reset, feedback_poll, feedback_get_stat

# Replace the descriptor builder's final set-length call. Insert the AC status
# endpoint before AS alt0; class-specific AC wTotalLength is unchanged.
feedback_descriptor:
    li a5, 226
    bne a0, a5, 9f
    li a5, 4
    bne a1, a5, 9f
    li a5, 0x62053
    lbu a5, 0(a5)
    li a4, 7
    bne a5, a4, 9f
    li a5, 0x68000
    addi a2, a5, 225
    addi a3, a5, 81
1:  lbu a4, 0(a2)
    sb a4, 9(a2)
    addi a2, a2, -1
    bgeu a2, a3, 1b
    la a2, status_descriptor
    li a4, 9
2:  lbu t0, 0(a2)
    sb t0, 0(a3)
    addi a2, a2, 1
    addi a3, a3, 1
    addi a4, a4, -1
    bnez a4, 2b
    li a4, 1
    sb a4, 36(a5)
    addi a0, a0, 9
9:  j original_set_descriptor_length

# Called in place of audio endpoint reset on bus reset and SET_CONFIGURATION.
# The original reset initializes both directions and preserves USBINDEX.
feedback_reset:
    li a5, 0x62018
    lbu a4, 0x3b(a5)
    li a3, 7
    bne a4, a3, 9f
    li a4, 0x17e72
    lbu a4, 0(a4)
    beqz a4, 9f          # only the product's high-resolution descriptor path
    sw zero, 0x438(a5)
    li a4, 0x280
    sh a4, 0x430(a5)
    lw a5, 0(a5)
    li a4, 2
    sb a4, 4(a5)
    li a4, 8
    sh a4, 0x14(a5)
    sh zero, 0x10(a5)
    lbu a4, 6(a5)
    andi a4, a4, -9
    sb a4, 6(a5)
9:  j original_audio_reset

# Main USB-mode loop: preserve original service, then post at most one pending
# work item. USB register access stays in the original USB worker task.
feedback_poll:
    addi sp, sp, -16
    sw ra, 12(sp)
    jal ra, original_usb_service
    li a5, 0x62018
    lbu a4, 0x3b(a5)
    li a3, 7
    bne a4, a3, 9f
    lbu a4, 0x3a(a5)
    li a3, 1
    bne a4, a3, 9f
    lw a4, 0(a5)
    lbu a4, 4(a4)
    li a3, 2
    bne a4, a3, 9f
    lbu a4, 0x43a(a5)
    bnez a4, 9f
    li a4, 0x4fb91
    lbu a4, 0(a4)
    lbu a3, 0xd(a5)
    bne a3, a4, 1f
    lbu a4, 0x438(a5)
    beqz a4, 9f
1:  li a4, 1
    sb a4, 0x43a(a5)
    li a0, 0x25
    lui a5, %hi(original_post_usb_event)
    addi a5, a5, %lo(original_post_usb_event)
    jalr ra, a5, 0
9:  lw ra, 12(sp)
    addi sp, sp, 16
    ret

# Branch hook in the class/interface IN request handler, with its original
# s0=EP0 context and s1=previous selected endpoint. Preserve a5 on fallthrough.
feedback_get_stat:
    lbu a0, 0x23(s0)      # replaced instruction
    li t0, 0xff
    bne a0, t0, 9f
    lhu t0, 0x22(s0)
    li t1, 0xffa1
    bne t0, t1, 9f
    lhu t0, 0x26(s0)
    li t1, 0x0201
    bne t0, t1, 9f
    lhu t0, 0x24(s0)
    bnez t0, 9f
    lhu t0, 0x28(s0)
    bnez t0, 9f
    li t0, 0x62053
    lbu t0, 0(t0)
    li t1, 7
    bne t0, t1, 9f
    # wLength=0 has no data phase. Use the stack's no-data status ACK path,
    # not its IN-data sender (which assumes a prepared EP0 FIFO/DMA length).
    # Sending another IN3 packet inside this request would also overwrite the
    # shared DMA command register. The regular USB task sends pending changes.
    sh zero, 0x10(s0)
    j original_ep0_no_data_ack
9:  j original_class_in_continue

status_descriptor:
    # UAC1 requires wMaxPacketSize=2 for an unshared status endpoint.
    # Hardware FIFO allocation has eight-byte granularity; only two bytes
    # are ever armed, regardless of that internal allocation size.
    .byte 9, 5, 0x83, 3, 2, 0, 10, 0, 0
.balign 2
