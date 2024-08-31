#!/usr/bin/env python3
import os, sys, subprocess

RISCV_MACHINE = '''
#include <stdint.h>
#define size_t uint32_t

struct user *u = 0;

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


def c2o(file, out='/tmp/c2o.o', includes=None, defines=None, opt='-O0', bits=64 ):
	if 'fedora' in os.uname().nodename:
		cmd = ['riscv64-linux-gnu-gcc']
	else:
		cmd = ['riscv64-unknown-elf-gcc']

	if bits==32:
		cmd.append('-march=rv32i')
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


def mkkernel(output='/tmp/two11bsd.elf'):
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

	if 'fedora' in os.uname().nodename:
		cmd = ['riscv64-linux-gnu-ld']
	else:
		cmd = ['riscv64-unknown-elf-ld']

	cmd += ['-march=rv32', '-m', 'elf32lriscv', '-o', output] + obs + macho
	print(cmd)
	subprocess.check_call(cmd)

if __name__=='__main__':
	mkkernel()
