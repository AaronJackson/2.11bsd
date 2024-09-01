#!/usr/bin/env python3
import os, sys, subprocess

RISCV_MACHINE = '''
#include <stdint.h>
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


def mkkernel(output='/tmp/two11bsd.elf', with_signals=False, with_fs=False, with_ufs=False, with_sync=False, with_clock=False, with_exec=False, with_socket=False, with_sysctl=False):
	defines = [
		'KERNEL',
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

	os.system('cp -v ./sys/h/*.h /tmp/bsd/sys/.')
	os.system('cp -v ./sys/machine/*.h /tmp/bsd/machine/.')
	os.system('cp -v ./sys/netinet/*.h /tmp/bsd/netinet/.')

	obs = []
	for name in os.listdir('./sys/sys/'):
		print(name)
		if not name.endswith('.c'): continue ## TODO parse tags

		if not with_ufs and name.startswith( ('ufs_syscalls', 'ufs_bio', 'ufs_alloc', 'ufs_bmap', 'ufs_subr', 'ufs_namei', 'ufs_inode', 'ufs_mount', 'ufs_fio') ): continue
		if not with_sync and name.startswith( ('kern_sync', 'vm_sched') ): continue
		if not with_clock and name.startswith('kern_clock'): continue
		if not with_exec and name.startswith( ('kern_exec', 'kern_fork', 'sys_process', 'vm_proc') ): continue
		if not with_socket and name.startswith( ('uipc_socket2', 'uipc_syscalls', 'sys_net', 'uipc_usrreq', 'uipc_proto') ): continue
		if not with_sysctl and name.startswith( 'kern_sysctl' ): continue
		if not with_fs and name.startswith( ('sys_inode','vm_swp') ): continue
		if not with_signals and name.startswith( 'kern_sig' ): continue

		o = c2o(
			os.path.join('./sys/sys', name), 
			out = '/tmp/%s.o' % name,
			includes=includes, defines=defines, bits=32)
		obs.append(o)

	rtmp = '/tmp/_riscv_.c'
	open(rtmp,'w').write(RISCV_MACHINE)
	o = c2o(
		rtmp, 
		out = '/tmp/_riscv_.o',
		includes=includes, defines=defines, bits=32)
	obs.append(o)

	macho = []
	for name in 'machdep'.split():
		o = c2o(
			'./sys/machine/%s.c' % name, 
			out = '/tmp/_riscv_%s.o' % name,
			includes=includes, defines=defines, bits=32)
		macho.append(o)

	for name in 'param'.split():
		o = c2o(
			'./sys/CURLY/%s.c' % name, 
			out = '/tmp/_riscv_%s.o' % name,
			includes=includes, defines=defines, bits=32)
		macho.append(o)



	if 'fedora' in os.uname().nodename:
		cmd = ['riscv64-linux-gnu-ld']
	else:
		cmd = ['riscv64-unknown-elf-ld']

	cmd += ['-march=rv32', '-m', 'elf32lriscv', '-o', output] + obs + macho
	print(cmd)
	subprocess.check_call(cmd)

if __name__=='__main__':
	mkkernel()
