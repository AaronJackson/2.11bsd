#!/usr/bin/env python3
# 2.11BSD RISC-V: BrentHarts 2024
import os, sys, subprocess, atexit

LINKER_SCRIPT = '''
ENTRY(_start)
MEMORY {} /* default */
. = 0x80000000;
SECTIONS {}
'''

ARCH = '''
#define MACHINE_BITS 32
#define BITS_PER_LONG MACHINE_BITS
#define bool _Bool
#define true 1
#define false 0
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef unsigned long u64;
typedef signed char i8;
typedef signed short i16;
typedef signed int i32;
typedef signed long i64;
typedef u32 size_t;
'''

UART = '''
#define UART_BASE 0x10000000
#define UART_RBR_OFFSET 0  /* In:  Recieve Buffer Register */
#define UART_THR_OFFSET 0  /* Out: Transmitter Holding Register */
#define UART_DLL_OFFSET 0  /* Out: Divisor Latch Low */
#define UART_IER_OFFSET 1  /* I/O: Interrupt Enable Register */
#define UART_DLM_OFFSET 1  /* Out: Divisor Latch High */
#define UART_FCR_OFFSET 2  /* Out: FIFO Control Register */
#define UART_IIR_OFFSET 2  /* I/O: Interrupt Identification Register */
#define UART_LCR_OFFSET 3  /* Out: Line Control Register */
#define UART_MCR_OFFSET 4  /* Out: Modem Control Register */
#define UART_LSR_OFFSET 5  /* In:  Line Status Register */
#define UART_MSR_OFFSET 6  /* In:  Modem Status Register */
#define UART_SCR_OFFSET 7  /* I/O: Scratch Register */
#define UART_MDR1_OFFSET 8 /* I/O:  Mode Register */
#define PLATFORM_UART_INPUT_FREQ 10000000
#define PLATFORM_UART_BAUDRATE 115200
static u8 *uart_base_addr = (u8 *)UART_BASE;
static void set_reg(u32 offset, u32 val){ writeu8(uart_base_addr + offset, val);}
static u32 get_reg(u32 offset){ return readu8(uart_base_addr + offset);}
static void uart_putc(u8 ch){ set_reg(UART_THR_OFFSET, ch);}
static void uart_print(char *str){ while (*str) uart_putc(*str++);}

static inline void uart_init(){
  u16 bdiv = (PLATFORM_UART_INPUT_FREQ + 8 * PLATFORM_UART_BAUDRATE) / (16 * PLATFORM_UART_BAUDRATE);
  set_reg(UART_IER_OFFSET, 0x00); /* Disable all interrupts */
  set_reg(UART_LCR_OFFSET, 0x80); /* Enable DLAB */
  if (bdiv) {
    set_reg(UART_DLL_OFFSET, bdiv & 0xff); /* Set divisor low byte */
    set_reg(UART_DLM_OFFSET, (bdiv >> 8) & 0xff); /* Set divisor high byte */
  }
  set_reg(UART_LCR_OFFSET, 0x03); /* 8 bits, no parity, one stop bit */
  set_reg(UART_FCR_OFFSET, 0x01); /* Enable FIFO */
  set_reg(UART_MCR_OFFSET, 0x00); /* No modem control DTR RTS */
  get_reg(UART_LSR_OFFSET); /* Clear line status */
  get_reg(UART_RBR_OFFSET); /* Read receive buffer */  
  set_reg(UART_SCR_OFFSET, 0x00); /* Set scratchpad */
}
'''

LIBC = r'''
void *memset(void *s, int c, size_t n){
  unsigned char *p = s;
  while (n--) *p++ = (unsigned char)c;
  return s;
}
void *memcpy(void *dest, const void *src, size_t n){
  unsigned char *d = dest;
  const unsigned char *s = src;
  while (n--) *d++ = *s++;
  return dest;
}
#define VRAM ((volatile u8 *)0x50000000)
void putpixel(int x, int y, char c){
	VRAM[y*320 + x] = c;
}
'''


VGA_S = r'''
	# PCI is at 0x30000000
	# VGA is at 00:01.0, using extended control regs (4096 bytes)
	# TODO: Scan for Vendor ID / Product ID
	la t0, 0x30000000|(1<<15)|(0<<12)
	# Set up frame buffer
	la t1, 0x50000008
	sw t1, 0x10(t0)
	# Set up I/O
	la t2, 0x40000000
	sw t2, 0x18(t0)
	# Enable memory accesses for this device
	lw a0, 0x04(t0)
	ori a0, a0, 0x02
	sw a0, 0x04(t0)
	lw a0, 0x04(t0)
	# Set up video mode somehow
	li t3, 0x60 # Enable LFB, enable 8-bit DAC
	sh t3, 0x508(t2)
	# Set Mode 13h by hand
	la a0, mode_13h_regs
	addi a1, t2, 0x400-0xC0
	la t3, 0xC0
	1:
		# Grab address
		lbu a3, 0(a0)
		beq a3, zero, 2f
		add a2, a1, a3
		# Grab index and data
		lb a4, 1(a0)
		lbu a5, 2(a0)
		# Advance a0
		addi a0, a0, 3
		# If this is for the attribute controller, treat it specially.
		blt a3, t3, 3f
		# If this is an external register, also treat it specially.
		blt a4, zero, 4f
			# Normal case
			sb a4, 0(a2)
			sb a5, 1(a2)
			j 1b
		3:
			# The attribute controller is a special case
			lb zero, 0xDA(a1)
			sb a4, 0(a2)
			sb a5, 0(a2)
			j 1b
		4:
			# External registers are also special but not as special as the attribute controller
			sb a5, 0(a2)
			j 1b
	2:
	# Set up a palette
	li t3, 0
	sb t3, 0x408(t2)
	li t3, 0
	li t4, 256*3
	la a0, initial_palette
	1:
		lb t5, 0(a0)
		sb t5, 0x409(t2)
		addi a0, a0, 1
		addi t3, t3, 1
		bltu t3, t4, 1b

'''

START_VGA_S = f'''
.text
.global _start
_start:
  bne a0, x0, _start # loop if hartid is not 0
  li sp, 0x80200000 # setup stack pointer
  {VGA_S}
  j firmware_main # jump to c entry
'''

MODE_13H = '''
mode_13h_regs:
	# Miscellaneous Output Register:
	# Just a single port. But bit 0 determines whether we use 3Dx or 3Bx.
	# So we need to set this early.
	.byte 0xC2, 0xFF, 0x63

	# Sequencer:
	# Disable reset here.
	.byte 0xC4, 0x00, 0x00

	# Attributes:
	# - Read 3DA to reset flip-flop
	# - Write 3C0 for address
	# - Write 3C0 for data
	.byte 0xC0, 0x00, 0x00
	.byte 0xC0, 0x01, 0x02
	.byte 0xC0, 0x02, 0x08
	.byte 0xC0, 0x03, 0x0A
	.byte 0xC0, 0x04, 0x20
	.byte 0xC0, 0x05, 0x22
	.byte 0xC0, 0x06, 0x28
	.byte 0xC0, 0x07, 0x2A
	.byte 0xC0, 0x08, 0x15
	.byte 0xC0, 0x09, 0x17
	.byte 0xC0, 0x0A, 0x1D
	.byte 0xC0, 0x0B, 0x1F
	.byte 0xC0, 0x0C, 0x35
	.byte 0xC0, 0x0D, 0x37
	.byte 0xC0, 0x0E, 0x3D
	.byte 0xC0, 0x0F, 0x3F

	.byte 0xC0, 0x30, 0x41
	.byte 0xC0, 0x31, 0x00
	.byte 0xC0, 0x32, 0x0F
	.byte 0xC0, 0x33, 0x00
	.byte 0xC0, 0x34, 0x00

	# Graphics Mode
	.byte 0xCE, 0x00, 0x00
	.byte 0xCE, 0x01, 0x00
	.byte 0xCE, 0x02, 0x00
	.byte 0xCE, 0x03, 0x00
	.byte 0xCE, 0x04, 0x00
	.byte 0xCE, 0x05, 0x40
	.byte 0xCE, 0x06, 0x05
	.byte 0xCE, 0x07, 0x00
	.byte 0xCE, 0x08, 0xFF

	# CRTC
	.byte 0xD4, 0x11, 0x0E # Do this to unprotect the registers

	.byte 0xD4, 0x00, 0x5F
	.byte 0xD4, 0x01, 0x4F
	.byte 0xD4, 0x02, 0x50
	.byte 0xD4, 0x03, 0x82
	.byte 0xD4, 0x04, 0x54
	.byte 0xD4, 0x05, 0x80
	.byte 0xD4, 0x06, 0xBF
	.byte 0xD4, 0x07, 0x1F
	.byte 0xD4, 0x08, 0x00
	.byte 0xD4, 0x09, 0x41
	.byte 0xD4, 0x0A, 0x20
	.byte 0xD4, 0x0B, 0x1F
	.byte 0xD4, 0x0C, 0x00
	.byte 0xD4, 0x0D, 0x00
	.byte 0xD4, 0x0E, 0xFF
	.byte 0xD4, 0x0F, 0xFF
	.byte 0xD4, 0x10, 0x9C
	.byte 0xD4, 0x11, 0x8E # Registers are now reprotected
	.byte 0xD4, 0x12, 0x8F, 0xD4, 0x13, 0x28, 0xD4, 0x14, 0x40, 0xD4, 0x15, 0x96, 0xD4, 0x16, 0xB9, 0xD4, 0x17, 0xA3

'''

vga_pal = [0x00, 0x00, 0x00,0x00, 0x00, 0x55,0x00, 0x00, 0xAA,0x00, 0x00, 0xFF,0x00, 0x55, 0x00,0x00, 0x55, 0x55,0x00, 0x55, 0xAA,0x00, 0x55, 0xFF,0x00, 0xAA, 0x00,0x00, 0xAA, 0x55,0x00, 0xAA, 0xAA,0x00, 0xAA, 0xFF,0x00, 0xFF, 0x00,0x00, 0xFF, 0x55,0x00, 0xFF, 0xAA,0x00, 0xFF, 0xFF,0x55, 0x00, 0x00,0x55, 0x00, 0x55,0x55, 0x00, 0xAA,0x55, 0x00, 0xFF,0x55, 0x55, 0x00,0x55, 0x55, 0x55,0x55, 0x55, 0xAA,0x55, 0x55, 0xFF,0x55, 0xAA, 0x00,0x55, 0xAA, 0x55,0x55, 0xAA, 0xAA,0x55, 0xAA, 0xFF,0x55, 0xFF, 0x00,0x55, 0xFF, 0x55,0x55, 0xFF, 0xAA,0x55, 0xFF, 0xFF,0xAA, 0x00, 0x00,0xAA, 0x00, 0x55,0xAA, 0x00, 0xAA,0xAA, 0x00, 0xFF,0xAA, 0x55, 0x00,0xAA, 0x55, 0x55,0xAA, 0x55, 0xAA,0xAA, 0x55, 0xFF,0xAA, 0xAA, 0x00,0xAA, 0xAA, 0x55,0xAA, 0xAA, 0xAA,0xAA, 0xAA, 0xFF,0xAA, 0xFF, 0x00,0xAA, 0xFF, 0x55,0xAA, 0xFF, 0xAA,0xAA, 0xFF, 0xFF,0xFF, 0x00, 0x00,0xFF, 0x00, 0x55,0xFF, 0x00, 0xAA,0xFF, 0x00, 0xFF,0xFF, 0x55, 0x00,0xFF, 0x55, 0x55,0xFF, 0x55, 0xAA,0xFF, 0x55, 0xFF,0xFF, 0xAA, 0x00,0xFF, 0xAA, 0x55,0xFF, 0xAA, 0xAA,0xFF, 0xAA, 0xFF,0xFF, 0xFF, 0x00,0xFF, 0xFF, 0x55,0xFF, 0xFF, 0xAA,0xFF, 0xFF, 0xFF,0x00, 0x00, 0x00,0x00, 0x00, 0x55,0x00, 0x00, 0xAA,0x00, 0x00, 0xFF,0x00, 0x55, 0x00,0x00, 0x55, 0x55,0x00, 0x55, 0xAA,0x00, 0x55, 0xFF,0x00, 0xAA, 0x00,0x00, 0xAA, 0x55,0x00, 0xAA, 0xAA,0x00, 0xAA, 0xFF,0x00, 0xFF, 0x00,0x00, 0xFF, 0x55,0x00, 0xFF, 0xAA,0x00, 0xFF, 0xFF,0x55, 0x00, 0x00,0x55, 0x00, 0x55,0x55, 0x00, 0xAA,0x55, 0x00, 0xFF,0x55, 0x55, 0x00,0x55, 0x55, 0x55,0x55, 0x55, 0xAA,0x55, 0x55, 0xFF,0x55, 0xAA, 0x00,0x55, 0xAA, 0x55,0x55, 0xAA, 0xAA,0x55, 0xAA, 0xFF,0x55, 0xFF, 0x00,0x55, 0xFF, 0x55,0x55, 0xFF, 0xAA,0x55, 0xFF, 0xFF,0xAA, 0x00, 0x00,0xAA, 0x00, 0x55,0xAA, 0x00, 0xAA,0xAA, 0x00, 0xFF,0xAA, 0x55, 0x00,0xAA, 0x55, 0x55,0xAA, 0x55, 0xAA,0xAA, 0x55, 0xFF,0xAA, 0xAA, 0x00,0xAA, 0xAA, 0x55,0xAA, 0xAA, 0xAA,0xAA, 0xAA, 0xFF,0xAA, 0xFF, 0x00,0xAA, 0xFF, 0x55,0xAA, 0xFF, 0xAA,0xAA, 0xFF, 0xFF,0xFF, 0x00, 0x00,0xFF, 0x00, 0x55,0xFF, 0x00, 0xAA,0xFF, 0x00, 0xFF,0xFF, 0x55, 0x00,0xFF, 0x55, 0x55,0xFF, 0x55, 0xAA,0xFF, 0x55, 0xFF,0xFF, 0xAA, 0x00,0xFF, 0xAA, 0x55,0xFF, 0xAA, 0xAA,0xFF, 0xAA, 0xFF,0xFF, 0xFF, 0x00,0xFF, 0xFF, 0x55,0xFF, 0xFF, 0xAA,0xFF, 0xFF, 0xFF,0x00, 0x00, 0x00,0x00, 0x00, 0x55,0x00, 0x00, 0xAA,0x00, 0x00, 0xFF,0x00, 0x55, 0x00,0x00, 0x55, 0x55,0x00, 0x55, 0xAA,0x00, 0x55, 0xFF,0x00, 0xAA, 0x00,0x00, 0xAA, 0x55,0x00, 0xAA, 0xAA,0x00, 0xAA, 0xFF,0x00, 0xFF, 0x00,0x00, 0xFF, 0x55,0x00, 0xFF, 0xAA,0x00, 0xFF, 0xFF,0x55, 0x00, 0x00,0x55, 0x00, 0x55,0x55, 0x00, 0xAA,0x55, 0x00, 0xFF,0x55, 0x55, 0x00,0x55, 0x55, 0x55,0x55, 0x55, 0xAA,0x55, 0x55, 0xFF,0x55, 0xAA, 0x00,0x55, 0xAA, 0x55,0x55, 0xAA, 0xAA,0x55, 0xAA, 0xFF,0x55, 0xFF, 0x00,0x55, 0xFF, 0x55,0x55, 0xFF, 0xAA,0x55, 0xFF, 0xFF,0xAA, 0x00, 0x00,0xAA, 0x00, 0x55,0xAA, 0x00, 0xAA,0xAA, 0x00, 0xFF,0xAA, 0x55, 0x00,0xAA, 0x55, 0x55,0xAA, 0x55, 0xAA,0xAA, 0x55, 0xFF,0xAA, 0xAA, 0x00,0xAA, 0xAA, 0x55,0xAA, 0xAA, 0xAA,0xAA, 0xAA, 0xFF,0xAA, 0xFF, 0x00,0xAA, 0xFF, 0x55,0xAA, 0xFF, 0xAA,0xAA, 0xFF, 0xFF,0xFF, 0x00, 0x00,0xFF, 0x00, 0x55,0xFF, 0x00, 0xAA,0xFF, 0x00, 0xFF,0xFF, 0x55, 0x00,0xFF, 0x55, 0x55,0xFF, 0x55, 0xAA,0xFF, 0x55, 0xFF,0xFF, 0xAA, 0x00,0xFF, 0xAA, 0x55,0xFF, 0xAA, 0xAA,0xFF, 0xAA, 0xFF,0xFF, 0xFF, 0x00,0xFF, 0xFF, 0x55,0xFF, 0xFF, 0xAA,0xFF, 0xFF, 0xFF,0x00, 0x00, 0x00,0x00, 0x00, 0x55,0x00, 0x00, 0xAA,0x00, 0x00, 0xFF,0x00, 0x55, 0x00,0x00, 0x55, 0x55,0x00, 0x55, 0xAA,0x00, 0x55, 0xFF,0x00, 0xAA, 0x00,0x00, 0xAA, 0x55,0x00, 0xAA, 0xAA,0x00, 0xAA, 0xFF,0x00, 0xFF, 0x00,0x00, 0xFF, 0x55,0x00, 0xFF, 0xAA,0x00, 0xFF, 0xFF,0x55, 0x00, 0x00,0x55, 0x00, 0x55,0x55, 0x00, 0xAA,0x55, 0x00, 0xFF,0x55, 0x55, 0x00,0x55, 0x55, 0x55,0x55, 0x55, 0xAA,0x55, 0x55, 0xFF,0x55, 0xAA, 0x00,0x55, 0xAA, 0x55,0x55, 0xAA, 0xAA,0x55, 0xAA, 0xFF,0x55, 0xFF, 0x00,0x55, 0xFF, 0x55,0x55, 0xFF, 0xAA,0x55, 0xFF, 0xFF,0xAA, 0x00, 0x00,0xAA, 0x00, 0x55,0xAA, 0x00, 0xAA,0xAA, 0x00, 0xFF,0xAA, 0x55, 0x00,0xAA, 0x55, 0x55,0xAA, 0x55, 0xAA,0xAA, 0x55, 0xFF,0xAA, 0xAA, 0x00,0xAA, 0xAA, 0x55,0xAA, 0xAA, 0xAA,0xAA, 0xAA, 0xFF,0xAA, 0xFF, 0x00,0xAA, 0xFF, 0x55,0xAA, 0xFF, 0xAA,0xAA, 0xFF, 0xFF,0xFF, 0x00, 0x00,0xFF, 0x00, 0x55,0xFF, 0x00, 0xAA,0xFF, 0x00, 0xFF,0xFF, 0x55, 0x00,0xFF, 0x55, 0x55,0xFF, 0x55, 0xAA,0xFF, 0x55, 0xFF,0xFF, 0xAA, 0x00,0xFF, 0xAA, 0x55,0xFF, 0xAA, 0xAA,0xFF, 0xAA, 0xFF,0xFF, 0xFF, 0x00,0xFF, 0xFF, 0x55,0xFF, 0xFF, 0xAA,0xFF, 0xFF, 0xFF]
def gen_pal():
	asm = [
		'initial_palette:',
		'	.byte %s' % ','.join( str(b) for b in vga_pal)
	]
	return '\n'.join(asm)


KLIB_NAMEI = '''
/*
 * Convert a pathname into a pointer to a locked inode.
 * This is a very central and rather complicated routine.
 * If the file system is not maintained in a strict tree hierarchy,
 * this can result in a deadlock situation (see comments in code below).
 *
 * The flag argument is LOOKUP, CREATE, or DELETE depending on whether
 * the name is to be looked up, created, or deleted. When CREATE or
 * DELETE is specified, information usable in creating or deleteing a
 * directory entry is also calculated. If flag has LOCKPARENT or'ed
 * into it and the target of the pathname exists, namei returns both
 * the target and its parent directory locked. When creating and
 * LOCKPARENT is specified, the target may not be ".".  When deleting
 * and LOCKPARENT is specified, the target may be ".", but the caller
 * must check to insure it does an irele and iput instead of two iputs.
 ......................
 	... see ufs_namei.c
*/
#include "namei.h"
struct inode* namei(struct nameidata *ndp){
	//TODO
}
'''

KLIB_COPYINOUT = '''
#include <stdint.h>

int copyin(const void *fromaddr, void *toaddr, size_t length) {
	// Check for invalid addresses or lengths
	if (!fromaddr || !toaddr || length % sizeof(uint32_t) != 0) {
		return -1;
	}

	// Ensure proper memory alignment for 32-bit words
	if ((uintptr_t)fromaddr & 3 || (uintptr_t)toaddr & 3) {
		return -1;
	}

	// Calculate the number of 32-bit words to copy
	size_t num_words = length / sizeof(uint32_t);

	// Copy 32-bit words using a loop
	for (size_t i = 0; i < num_words; ++i) {
		uint32_t word = *((uint32_t *)fromaddr + i);
		*((uint32_t *)toaddr + i) = word;
	}

	return 0; // Success
}

int copyout(const void *fromaddr, void *toaddr, size_t length) {
	// Check for invalid addresses or lengths
	if (!fromaddr || !toaddr || length % sizeof(uint32_t) != 0) {
		return -1;
	}

	// Ensure proper memory alignment for 32-bit words
	if ((uintptr_t)fromaddr & 3 || (uintptr_t)toaddr & 3) {
		return -1;
	}

	// Calculate the number of 32-bit words to copy
	size_t num_words = length / sizeof(uint32_t);

	// Copy 32-bit words using a loop
	for (size_t i = 0; i < num_words; ++i) {
		uint32_t word = *((uint32_t *)fromaddr + i);
		*((uint32_t *)toaddr + i) = word;
	}

	return 0; // Success
}


'''

KLIB_TODO = '''
#include "param.h"
#include "../machine/seg.h"
#include "../machine/iopage.h"

#include "dir.h"
#include "inode.h"
#include "user.h"
#include "proc.h"
#include "fs.h"
#include "map.h"
#include "buf.h"


int vcopyin(const void *fromaddr, void *toaddr, size_t length) {
	// Check for invalid addresses or lengths
	if (!fromaddr || !toaddr || length == 0) {
		return -1;
	}

	// Handle the case where fromaddr, toaddr, or length is odd
	if ((uintptr_t)fromaddr & 1 || (uintptr_t)toaddr & 1 || length & 1) {
		// Handle individual bytes or half-words as needed
		while (length > 0) {
			if (length >= 2) {
				// Copy a half-word (16 bits)
				uint16_t half_word = *((uint16_t *)fromaddr);
				*((uint16_t *)toaddr) = half_word;
				fromaddr += 2;
				toaddr += 2;
				length -= 2;
			} else {
				// Copy a single byte
				uint8_t byte = *((uint8_t *)fromaddr);
				*((uint8_t *)toaddr) = byte;
				fromaddr += 1;
				toaddr += 1;
				length -= 1;
			}
		}
	}

	// Calculate the number of 32-bit words to copy
	size_t num_words = length / sizeof(uint32_t);

	// Copy 32-bit words using a loop
	for (size_t i = 0; i < num_words; ++i) {
		uint32_t word = *((uint32_t *)fromaddr + i);
		*((uint32_t *)toaddr + i) = word;
	}

	// Handle any remaining bytes
	size_t remaining_bytes = length % sizeof(uint32_t);
	if (remaining_bytes > 0) {
		const uint8_t *src_bytes = (const uint8_t *)fromaddr + (num_words * sizeof(uint32_t));
		uint8_t *dst_bytes = (uint8_t *)toaddr + (num_words * sizeof(uint32_t));

		for (size_t i = 0; i < remaining_bytes; ++i) {
			dst_bytes[i] = src_bytes[i];
		}
	}
	return 0; // Success
}

int vcopyout(const void *fromaddr, void *toaddr, size_t length) {
	// Check for invalid addresses or lengths
	if (!fromaddr || !toaddr || length == 0) {
		return -1;
	}

	// Handle the case where fromaddr, toaddr, or length is odd
	if ((uintptr_t)fromaddr & 1 || (uintptr_t)toaddr & 1 || length & 1) {
		// Implement the logic for copying individual bytes or half-words as needed
		while (length > 0) {
			if (length >= 2) {
				// Copy a half-word (16 bits)
				uint16_t half_word = *((uint16_t *)fromaddr);
				*((uint16_t *)toaddr) = half_word;
				fromaddr += 2;
				toaddr += 2;
				length -= 2;
			} else {
				// Copy a single byte
				uint8_t byte = *((uint8_t *)fromaddr);
				*((uint8_t *)toaddr) = byte;
				fromaddr += 1;
				toaddr += 1;
				length -= 1;
			}
		}
	}

	// Calculate the number of 32-bit words to copy
	size_t num_words = length / sizeof(uint32_t);

	// Copy 32-bit words using a loop
	for (size_t i = 0; i < num_words; ++i) {
		uint32_t word = *((uint32_t *)fromaddr + i);
		*((uint32_t *)toaddr + i) = word;
	}

	// Handle any remaining bytes
	size_t remaining_bytes = length % sizeof(uint32_t);
	if (remaining_bytes > 0) {
		const uint8_t *src_bytes = (const uint8_t *)fromaddr + (num_words * sizeof(uint32_t));
		uint8_t *dst_bytes = (uint8_t *)toaddr + (num_words * sizeof(uint32_t));

		for (size_t i = 0; i < remaining_bytes; ++i) {
			dst_bytes[i] = src_bytes[i];
		}
	}

	return 0; // Success
}

int copystr(const char *fromaddr, char *toaddr, size_t maxlength, size_t *lencopied) {
	// Check for invalid addresses or maxlength
	if (!fromaddr || !toaddr || maxlength == 0) {
		return -1;
	}

	// Copy characters until a null terminator or maxlength is reached
	size_t copied = 0;
	while (copied < maxlength) {
		char c = *fromaddr++;
		if (c == '\0') {
			break;
		}
		*toaddr++ = c;
		copied++;
	}

	// Check if maxlength was exceeded
	if (copied == maxlength && *fromaddr != '\0') {
		return -1;
	}

	// Update lencopied if provided
	if (lencopied != NULL) {
		*lencopied = copied + 1; // Include the null terminator
	}

	return 0; // Success
}


//#define DEV_BSIZE 512
//#define RW 0x03
// The default value of 0x80000000 is a typical starting address for user-level virtual memory segments. 
#define SEG5 0x80000000
#define VIRTUAL_BASE 0x80000000 // Example virtual base address

/*
void mapseg5(uint16_t paddr, uint16_t flags) {
	// Calculate the virtual address
	uint32_t vaddr = VIRTUAL_BASE + (paddr & 0xFFFF0000);
	// Write the physical address to the virtual address
	*((uint32_t *)vaddr) = paddr;
}
*/

uint32_t mapinxxx(struct buf *bp) {
	uint32_t offset = bp->b_bcount & 077;
	uint32_t paddr = bftopaddr(bp);
	mapseg5((uint16_t)paddr, (uint16_t)(((uint32_t)DEV_BSIZE << 2) | (uint32_t)RW));
	return (SEG5 + offset);
}

struct user u = {};
'''


RISCV_MACHINE_MIN = '''
#include "param.h"
#include "user.h"
#include "proc.h"
#include "mbuf.h"

int	cmask = CMASK;
int	netoff = 1;
struct user u = {};

struct	domain *domains;
struct	mbstat mbstat;
int	 m_want;
char mclrefcnt[NMBCLUSTERS + 1];
int	nmbclusters;
struct  mbuf *mfree;
struct  mbuf *mclfree;


void firmware_main(){
	putpixel(10,10,100);
	putpixel(10,11,100);
	uart_init();
	putpixel(11,11,10);
	putpixel(12,12,32);
	uart_print("hello 2.11BSD\\n");
	struct proc *p;
	//p = &proc[0];
	//p->p_addr = *ka6;
	p->p_stat = SRUN;
	p->p_flag |= SLOAD|SSYS;
	p->p_nice = NZERO;

	u.u_procp = p;			/* init user structure */
	u.u_ap = u.u_arg;
	u.u_cmask = cmask;
	u.u_lastfile = -1;

#ifdef INET
	if (netoff = netinit())
		printf("netinit failed\\n");
	else
		{
		#define hz 100
		NETSETHZ();
		NETSTART();
		}
#endif

}

/*
 * SKcall(func, nbytes, a1, ..., aN)
 *
 * C-call from supervisor to kernel.
 * Calls func(a1, ..., aN) in kernel mode.
*/

void SKcall(void *func, int nbytes, ...){
	//TODO
}

/*
 * KScall(func, nbytes, a1, ..., aN)
 *
 * C-call from kernel to supervisor.
 * Calls func(a1, ..., aN) in supervisor mode.
*/
void KScall(void *func, int nbytes, ...){
	//TODO
}

''' + KLIB_COPYINOUT


def c2o(file, out='/tmp/c2o.o', includes=None, defines=None, opt='-O0', bits=64 ):
	if 'fedora' in os.uname().nodename:
		cmd = ['riscv64-linux-gnu-gcc']
	else:
		cmd = ['riscv64-unknown-elf-gcc']

	if bits==32:
		cmd.append('-march=rv32imac')
		cmd.append('-mabi=ilp32')

	cmd += [
		'-c', '-mcmodel=medany', '-fomit-frame-pointer', '-ffunction-sections',
		'-ffreestanding', '-nostdlib', '-nostartfiles', '-nodefaultlibs', 
		opt, '-g', '-o', out, file
	]
	if includes:
		for inc in includes:
			if not inc.startswith('-I'): inc = '-I'+inc
			cmd.append(inc)
	if defines:
		for d in defines:
			if not d.startswith('-D'): d = '-D'+d
			cmd.append(d)
	
	print(cmd)
	subprocess.check_call(cmd)
	return out


def mkkernel(output='/tmp/two11bsd.elf', 
		with_signals=False, with_fs=False, with_ufs=False, with_sync=False, with_clock=False, with_exec=False, 
		with_socket=False, with_sysctl=False, with_tty=False, with_exit=False, with_subr=False, with_generic=False,
		with_machdep=False, with_resource=False, with_log=False, with_sysent=False, with_malloc=False,
		with_kern_accounting=False, ## "This module is a shadow of its former self. SHOULD REPLACE THIS WITH A DRIVER THAT CAN BE READ TO SIMPLIFY.""
		with_kern_xxx=False, with_init_main=False,
		allow_unresolved=False, vga=False, 
		gdb='--gdb' in sys.argv or '--gdb-step' in sys.argv,
		):
	defines = [
		'KERNEL', 
		#'SUPERVISOR',
		'FREAD=0x01',
		'FWRITE=0x10',
		'O_FSYNC=0x0',
		'FNONBLOCK=0x0',
		## kern_descrip.c
		'LOCK_UN=0x0',
		'FSHLOCK=0x0',
		'FEXLOCK=0x0',
		'LOCK_SH=0x0',
		'LOCK_EX=0x0',
		'FCNTLFLAGS=0x0',
		## uipc_usreq.c
		'FDEFER=0x0',
		'FMARK=0x0',
		## sys_inode.c
		'LOCK_NB=0x0',
		'FFSYNC=0x0',
		## ufs_syscalls.c
		'FMASK=0x0',
		'O_EXLOCK=0x0',
		'O_SHLOCK=0x0',
	]

	includes = [
		'./sys/h', 
		'./include', 
		'/tmp/bsd',
		'./sys/GENERIC',  ## for acc.h required by sys_net.c
		#'./sys/QT',  ## GENERIC?CURLY? for acc.h required by sys_net.c
	]
	if not os.path.isdir('/tmp/bsd'): os.mkdir('/tmp/bsd')
	if not os.path.isdir('/tmp/bsd/sys'): os.mkdir('/tmp/bsd/sys')
	if not os.path.isdir('/tmp/bsd/machine'): os.mkdir('/tmp/bsd/machine')
	if not os.path.isdir('/tmp/bsd/netinet'): os.mkdir('/tmp/bsd/netinet')
	if with_socket:
		if not os.path.isdir('/tmp/bsd/net'): os.mkdir('/tmp/bsd/net')
		os.system('cp -v ./sys/net/*.h /tmp/bsd/net/.')
		defines.append('INET')


	os.system('cp -v ./sys/h/*.h /tmp/bsd/sys/.')
	os.system('cp -v ./sys/machine/*.h /tmp/bsd/machine/.')
	os.system('cp -v ./sys/netinet/*.h /tmp/bsd/netinet/.')

	obs = []
	for name in os.listdir('./sys/sys/'):
		print(name)
		if not name.endswith('.c'): continue ## TODO parse tags

		if not with_ufs and name.startswith( ('ufs_dsort','ufs_disksubr','ufs_syscalls', 'ufs_bio', 'ufs_alloc', 'ufs_bmap', 'ufs_subr', 'ufs_namei', 'ufs_inode', 'ufs_mount', 'ufs_fio') ): continue
		if not with_sync and name.startswith( ('kern_sync', 'vm_sched') ): continue
		if not with_clock and name.startswith( ('kern_clock', 'kern_time') ): continue
		if not with_exec and name.startswith( ('kern_prot','kern_proc','kern_exec', 'kern_fork', 'sys_process', 'vm_proc', 'sys_pipe') ): continue
		if not with_socket and name.startswith( ('sys_kern', 'uipc_socket2', 'uipc_syscalls', 'sys_net', 'uipc_usrreq', 'uipc_proto') ): continue
		if not with_sysctl and name.startswith( 'kern_sysctl' ): continue
		if not with_fs and name.startswith( ('vm_text','vfs_vnops','sys_inode','vm_swap', 'vm_swp', 'kern_descrip', 'quota_sys') ): continue
		if not with_signals and name.startswith( 'kern_sig' ): continue
		if not with_tty and name.startswith('tty'): continue
		if not with_resource and name.startswith('kern_resource'): continue
		if not with_log and name.startswith('subr_log'): continue
		if not with_sysent and name.startswith('init_sysent'): continue
		if not with_malloc and name.startswith('kern_mman'): continue
		if not with_exit and name.startswith('kern_exit'): continue
		if not with_generic and name.startswith('sys_generic'): continue
		if not with_kern_accounting and name.startswith('kern_acct'): continue
		if not with_kern_xxx and name.startswith('kern_xxx'): continue  ## defines reboot()
		if not with_subr and 'subr' in name: continue
		if not with_init_main and name.startswith('init_main'):
			continue

		if name.startswith('uipc_'):
			defs = list(defines)
			defs.append('SUPERVISOR')
			#if name != 'uipc_usrreq.c':
			#	defs.remove('KERNEL')
		else:
			defs = defines

		o = c2o(
			os.path.join('./sys/sys', name), 
			out = '/tmp/%s.o' % name,
			includes=includes, defines=defs, bits=32)
		obs.append(o)


	defines.append('SUPERVISOR')
	rtmp = '/tmp/_riscv_.c'
	C = [ARCH, UART, LIBC, RISCV_MACHINE_MIN]

	if not with_ufs and with_socket:
		C.append(KLIB_NAMEI)

	open(rtmp,'w').write('\n'.join(C))
	o = c2o(
		rtmp, 
		out = '/tmp/_riscv_.o',
		includes=includes, defines=defines, bits=32)
	obs.append(o)

	macho = []
	if with_machdep:
		for name in 'machdep'.split():
			o = c2o(
				'./sys/machine/%s.c' % name, 
				out = '/tmp/_riscv_%s.o' % name,
				includes=includes, defines=defines, bits=32)
			macho.append(o)

	if False:
		for name in 'param'.split():
			o = c2o(
				'./sys/CURLY/%s.c' % name, 
				out = '/tmp/_riscv_%s.o' % name,
				includes=includes, defines=defines, bits=32)
			macho.append(o)

	if vga:
		tmps = '/tmp/__bsd_vga__.s'
		asm = [
			START_VGA_S,
			#gen_trap_s(),
			'.section .rodata', 
			MODE_13H, gen_pal()
		]
		open(tmps,'wb').write('\n'.join(asm).encode('utf-8'))
		o = c2o(tmps, out='/tmp/libbsd_vga.o', bits=32)
		macho.append(o)


	if 'fedora' in os.uname().nodename:
		cmd = ['riscv64-linux-gnu-ld']
	else:
		cmd = ['riscv64-unknown-elf-ld']

	if allow_unresolved:
		cmd.append('--unresolved-symbols=ignore-in-object-files')

	tmpld = '/tmp/linker.ld'
	open(tmpld,'wb').write(LINKER_SCRIPT.encode('utf-8'))
	cmd += ['-T',tmpld]


	cmd += ['-march=rv32', '-m', 'elf32lriscv', '-o', output] + obs + macho
	print(cmd)
	subprocess.check_call(cmd)

	cmd = ['riscv64-linux-gnu-objdump', '-d', output]
	print(cmd)
	subprocess.check_call(cmd)

	cmd = [
		'qemu-system-riscv32',
		'-M', 'virt',
		'-m', 'size=1G',
		'-serial', 'stdio',
		'-device', 'VGA',
		'--no-reboot',
		'-bios', output,
	]
	print(cmd)
	if gdb:
		cmd += ['-S','-gdb', 'tcp:localhost:1234,server,ipv4']
		print(cmd)
		proc = subprocess.Popen(cmd)
		atexit.register(lambda:proc.kill())
	else:
		print(cmd)
		subprocess.check_call(cmd)

	if gdb:
		cmd = ['gdb-multiarch', '--batch', '--command=/tmp/debug_bsd.gdb', output]

		if os.path.isfile('/usr/bin/konsole'):
			cmd = ['konsole', '--separate', '--hold', '-e', ' '.join(cmd)]
		else:
			cmd = ['xterm', '-hold', '-e', ' '.join(cmd)]

		gdb_script = []
		gdb_script.append('set architecture riscv:rv32')
		gdb_script += [
			'target remote :1234',
			'info registers',
		]


		if '--gdb-step' in sys.argv:
			step1 = 10
			step2 = 1
			for aidx, arg in enumerate(sys.argv):
				if arg=='--gdb-step':
					try:
						step1 = int(sys.argv[aidx+1])
						step2 = int(sys.argv[aidx+2])
					except: pass
			for i in range(step1):
				gdb_script += [
					"echo '----------------------'",
					'echo',
					'bt',
					'stepi %s' % step2,
					'info registers',
				]
			gdb_script.append('continue')

		else:
			gdb_script += [
			'continue',
			'info registers',
			'bt',
			]

		open('/tmp/debug_bsd.gdb', 'wb').write('\n'.join(gdb_script).encode('utf-8'))
		print(cmd)
		gdb = subprocess.check_call(cmd)


	return output

if __name__=='__main__':
	if '--inet' in sys.argv:
		mkkernel(with_socket=True)
	elif '--tty' in sys.argv:
		mkkernel(with_socket=True, with_tty=True)
	elif '--micro' in sys.argv:
		mkkernel(
			with_socket=True, with_tty=True, with_clock=True, with_sync=True, 
			with_signals=True, with_ufs=True,
		)
	elif '--all' in sys.argv:
		mkkernel(
			with_signals=True, with_fs=True, with_ufs=True, with_sync=True, with_clock=True, with_exec=True, 
			with_socket=True, with_sysctl=True, with_tty=True, with_exit=True, with_subr=True, with_generic=True,
			with_resource=True, with_log=True, with_sysent=True, with_malloc=True,
			with_kern_xxx=True, with_init_main=True,
		)
	elif '--vga' in sys.argv:
		mkkernel(
			with_socket=True, with_tty=True, with_clock=True, with_sync=True, with_signals=True, with_ufs=True,
			allow_unresolved=True, vga=True,
		)
	else:
		mkkernel()
