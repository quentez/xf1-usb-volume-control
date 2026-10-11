OUTPUT_ARCH(riscv)
SECTIONS {
  .feedback_core 0x1000c608 : { *(.feedback_core) }
  ASSERT(SIZEOF(.feedback_core) <= 0x1f8, "Core exceeds verified padding")
  .feedback_setup 0x10023410 : { *(.feedback_setup) }
  ASSERT(SIZEOF(.feedback_setup) <= 0x1f0, "Setup exceeds verified padding")
  /DISCARD/ : { *(.riscv.attributes) }
}
original_start_transfer = 0x1000eb90;
original_select_endpoint = 0x1000e840;
original_usb_task_loop = 0x2781a;
original_get_volume = 0x1000d89e;
original_set_descriptor_length = 0x1009b512;
original_audio_reset = 0x1000d9a8;
original_usb_service = 0x1000ef3c;
original_post_usb_event = 0x277d8;
original_ep0_no_data_ack = 0x1000e142;
original_class_in_continue = 0x1000e474;
