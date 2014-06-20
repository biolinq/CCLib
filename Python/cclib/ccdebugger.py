#
# The MIT License (MIT)
# 
# Copyright (c) 2014 Ioannis Charalampidis
# 
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
# 
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#

import serial
import struct
import math
import time

# Command constants
CMD_ENTER    = 0x01
CMD_EXIT     = 0x02
CMD_CHIP_ID  = 0x03
CMD_STATUS   = 0x04
CMD_PC       = 0x05
CMD_STEP     = 0x06
CMD_EXEC_1   = 0x07
CMD_EXEC_2   = 0x08
CMD_EXEC_3   = 0x09
CMD_BRUSTWR  = 0x0A
CMD_RD_CFG   = 0x0B
CMD_WR_CFG   = 0x0C
CMD_PING     = 0xF0

# Response constants
ANS_OK       = 0x01
ANS_ERROR    = 0x02

class CCDebugger:
	"""
	
	CC.Debuger class which uses the CCLib_proxy-compatible arduino firmware.

	Because the CCLib_proxy was used for experimentation with the CCDebugger protocol,
	all the higher-level logic is implemented in this class. In order to cope with the
	performance issues, a binary serial protocol was used.

	The overall flash writing operations are very good, however reading is much slower.

	!!! WARNING !!!

	The higher-level functions are *TAILORED* for CC2540/41 SOC (BLE112,BLE113). 
	DO NOT USE them for ANY other chip!

	"""

	def __init__(self, port):
		"""
		Initialize serial port
		"""

		# Open port
		try:
			self.ser = serial.Serial(port, timeout=1)
		except:
			raise IOError("Could not open port %s" % port)

		# Ping
		if self.ping():
			print "Using CCDebugger on port %s" % self.ser.name 
		else:
			raise IOError("Could not find CCLib_proxy device on port %s" % self.ser.name)

		# Get chip info & ID
		self.chipID = self.getChipID()
		self.chipInfo = self.getChipInfo()
		self.debugConfig = self.readConfig()
		self.debugStatus = 0

		# Validate chip
		if (self.chipID & 0xff00) != 0x8d00:
			raise IOError("This class works ONLY with CC2540 TI chips!")

	def sendFrame(self, cmd, c1=0,c2=0,c3=0 ):
		"""
		Send the specified frame to the output queue
		"""

		# Send the 4-byte command frame
		self.ser.write( chr(cmd)+chr(c1)+chr(c2)+chr(c3) )
		self.ser.flush()

		# Check if we are waiting for response
		status = ord(self.ser.read())
		if status != ANS_OK:
			status = ord(self.ser.read())
			raise IOError("CCDebugger responded with an error (0x%02x)" % status)

		# Otherwise we are good
		return True

	###############################################
	# Low-level functions
	###############################################

	def ping(self):
		"""
		Send a PING frame
		"""
		return self.sendFrame(CMD_PING)


	def enter(self):
		"""
		Enter in debug mode
		"""
		return self.sendFrame(CMD_ENTER)

	def exit(self):
		"""
		Exit from debug mode by resuming the CPU
		"""
		return self.sendFrame(CMD_EXIT)

	def readConfig(self):
		"""
		Read debug configuration
		"""
		if not self.sendFrame(CMD_RD_CFG):
			return 0

		# Read debug config
		b1 = ord(self.ser.read())
		return b1

	def writeConfig(self, config):
		"""
		Read debug configuration
		"""
		if not self.sendFrame(CMD_WR_CFG, config):
			return 0

		# Read debug config
		b1 = ord(self.ser.read())
		self.debugConfig = config
		self.debugStatus = b1
		return b1

	def step(self):
		"""
		Step a single instruction
		"""
		if not self.sendFrame(CMD_STEP):
			return 0

		# Read accumulator
		b1 = ord(self.ser.read())
		return b1

	def getChipID(self):
		"""
		Return the ChipID as read from the chip
		"""
		
		# Execute command CMD_CHIP_ID
		if not self.sendFrame(CMD_CHIP_ID):
			return False
		
		# Read Chip ID
		b1 = ord(self.ser.read())
		b2 = ord(self.ser.read())
		return (b1 <<  8) | b2

	def getPC(self):
		"""
		Return the PC position as read from the chip
		"""
		
		# Execute command CMD_CHIP_ID
		if not self.sendFrame(CMD_PC):
			return False
		
		# Read Program Counter
		b1 = ord(self.ser.read())
		b2 = ord(self.ser.read())
		return (b1 <<  8) | b2

	def instr(self, c1, c2=None, c3=None):
		"""
		Execute a debug instruction
		"""

		# Check how many bytes are we passing
		if (c2 == None):
			if not self.sendFrame(CMD_EXEC_1, c1):
				return False
		elif (c3 == None):
			if not self.sendFrame(CMD_EXEC_2, c1, c2):
				return False
		else:
			if not self.sendFrame(CMD_EXEC_3, c1, c2, c3):
				return False

		# Read accumulator
		b1 = ord(self.ser.read())
		return b1

	def instri(self, c1, i1):
		"""
		Execute a debug instruction with 16-bit constant
		"""

		# Split short in high/low order bytes
		cHigh = (i1 >> 8) & 0xFF
		cLow = (i1 & 0xFF)

		# Send instruction
		if not self.sendFrame(CMD_EXEC_3, c1, cHigh, cLow):
			return False

		# Read accumulator
		b1 = ord(self.ser.read())
		return b1

	def brustWrite(self, data):
		"""
		Perform a brust-write operation which allows us to write
		up to 2Kb in the DBGDATA register.
		"""

		# Validate length
		length = len(data)
		if length > 2048:
			return False

		# Split length in high/low order bytes
		cHigh = (length >> 8) & 0xFF
		cLow = (length & 0xFF)

		# Prepare for BRUST frame transmission
		if not self.sendFrame(CMD_BRUSTWR, cHigh, cLow):
			return False

		# Start sending data
		for b in data:
			self.ser.write(chr(b & 0xFF))
		self.ser.flush()

		# Handle response
		status = ord(self.ser.read())
		if status != ANS_OK:
			status = ord(self.ser.read())
			raise IOError("CCDebugger responded with an error (0x%02x)" % status)

		# Read debug config
		self.debugStatus = ord(self.ser.read())
		return True
		

	###############################################
	# Data reading
	###############################################

	def readXDATA( self, offset, size ):
		"""
		Read any size of buffer from the XDATA region
		"""

		# Setup DPTR
		a = self.instri( 0x90, offset )		# MOV DPTR,#data16

		# Prepare ans array
		ans = []

		# Read bytes
		for i in range(0, size):
			a = self.instr ( 0xE0 )			# MOVX A,@DPTR
			ans.append(a)
			a = self.instr ( 0xA3 )			# INC DPTR

		# Return ans
		return ans

	def writeXDATA( self, offset, bytes ):
		"""
		Write any size of buffer in the XDATA region
		"""

		# Setup DPTR
		a = self.instri( 0x90, offset )		# MOV DPTR,#data16

		# Read bytes
		for b in bytes:
			a = self.instr ( 0x74, b )		# MOV A,#data
			a = self.instr ( 0xF0 )			# MOVX @DPTR,A
			a = self.instr ( 0xA3 )			# INC DPTR

		# Return bytes written
		return len(bytes)

	def readCODE( self, offset, size ):
		"""
		Read any size of buffer from the XDATA+0x8000 (code-mapped) region
		"""

		# Pick the code bank this code chunk belongs to
		fBank = int(offset / 0x8000 )
		self.selectXDATABank( fBank )

		# Recalibrate offset
		offset -= fBank * 0x8000

		# Read XDATA-mapped CODE region
		return self.readXDATA( 0x8000 + offset, size )


	def getRegister( self, reg ):
		"""
		Return the value of the given register
		"""
		return self.instr( 0xE5, reg )		# MOV A,direct

	def setRegister( self, reg, v ):
		"""
		Update the value of the 
		"""
		return self.instr( 0x75, reg, v )	# MOV direct,#data

	def selectXDATABank(self, bank):
		"""
		Select XDATA bank from the Memory Arbiter Control register
		"""
		a = self.getRegister( 0xC7 )
		a = (a & 0xF8) | (bank & 0x07)
		return self.setRegister( 0xC7, a )

	def selectFlashBank(self, bank):
		"""
		Select a bank for 
		"""
		return self.setRegister( 0x9F, bank & 0x07 )


	###############################################
	# Chip information
	###############################################

	def getSerial(self):
		"""
		Read the IEEE address from the 0x780E register
		"""

		# Serial number is 6 bytes, stored on 0x780E
		bytes = self.readXDATA( 0x780E, 6 )

		# Build serial number string
		serial = ""
		for i in range(5,0,-1):
			serial += "%02x" % bytes[i]

		# Return serial
		return serial

	def getChipInfo(self):
		"""
		Analyze chip info registers
		"""

		# Get chip info registers
		chipInfo = self.readXDATA(0x6276, 2)

		# Extract the useful info
		return {
			'flash' : pow(2, 4 + ((chipInfo[0] & 0x70) >> 4)), # in Kb
			'usb'	: (chipInfo[0] & 0x08) != 0, # in Kb
			'sram'	: (chipInfo[1] & 0x07) + 1
		}

	def getInfoPage(self):
		"""
		Return the read-only information page (2kb)
		"""

		# Read XDATA
		data = self.readXDATA( 0x7800, 0x800 )

		# Get license key
		return data

	def getBLEInfoPage(self):
		"""
		Return the Bluegiga information page (last)
		"""

		# Read the last 64 bytes from the last FLASH page
		data = self.readCODE( 0x1ffc0, 0x40 )

		# Get the information page
		return data

	def getBLEInfo(self):
		"""
		Return the translated Bluegiga information page (last)
		"""

		# Get page data
		page = self.getBLEInfoPage()

		# Convert license to string
		strLic = "".join( "%02x" % x for x in page[7:39] )

		# Convert address to string
		strBTAddr = "".join( "%02x:" % x for x in page[42:48] )
		strBTAddr = strBTAddr[0:len(strBTAddr)-1]

		# Return translated information
		return {
			"license" : strLic,
			"hwver"   : page[39],
			"btaddr"  : strBTAddr,
			"lockbits": page[48:64]
		}

	###############################################
	# DMA functions
	###############################################

	def pauseDMA(self, pause):
		"""
		Pause/Unpause DMA in debug mode
		"""
		# Get current debug config
		a = self.readConfig()
		# Update
		if pause:
			a |= 0x4
		else:
			a &= ~0x4
		# Commit
		self.writeConfig(a)

	def configDMAChannel(self, index, srcAddr, dstAddr, trigger, vlen=0, tlen=1, 
		word=False, transferMode=0, srcInc=0, dstInc=0, interrupt=False, m8=True, 
		priority=0, memBase=0x1000):
		"""
		Create a DMA buffer and place it in memory
		"""

		# Calculate numeric flags
		nword = 0
		if word:
			nword = 1
		nirq = 0
		if interrupt:
			nirq = 1
		nm8 = 1
		if m8:
			nm8 = 0

		# Prepare DMA configuration bytes
		config = [
			(srcAddr >> 8) & 0xFF,		# 0: SRCADDR[15:8]
			(srcAddr & 0xFF),			# 1: SRCADDR[7:0]
			(dstAddr >> 8) & 0xFF,		# 2: DESTADDR[15:8]
			(dstAddr & 0xFF),			# 3: DESTADDR[7:0]
			(vlen & 0x07) << 5 |		# 4: VLEN[2:0]
			((tlen >> 8) & 0x1F),		# 4: LEN[12:8]
			(tlen & 0xFF),				# 5: LEN[7:0]
			(nword << 7) |				# 6: WORDSIZE
			(transferMode << 5) |		# 6: TMODE[1:0]
			(trigger & 0x1F),			# 6: TRIG[4:0]
			((srcInc & 0x03) << 6) |	# 7: SRCINC[1:0]
			((dstInc & 0x03) << 4) |	# 7: DESTINC[1:0]
			(nirq << 3) |				# 7: IRQMASK
			(nm8 << 2) |				# 7: M8
			(priority & 0x03)			# 7: PRIORITY[1:0]
		]

		# Pick an offset in memory to store the configuration
		memAddr = memBase + index*8
		self.writeXDATA( memAddr, config )

		# Split address in high/low
		cHigh = (memAddr >> 8) & 0xFF
		cLow = (memAddr & 0xFF)

		# Update DMA registers
		if index == 0:
			self.instr( 0x75, 0xD4, cLow  ) # MOV direct,#data @ DMA0CFGL
			self.instr( 0x75, 0xD5, cHigh ) # MOV direct,#data @ DMA0CFGH

		else:

			# For DMA1+ they reside one after the other, starting
			# on the base address of the first in DMA1CFGH:DMA1CFGL
			memAddr = memBase + 8
			cHigh = (memAddr >> 8) & 0xFF
			cLow = (memAddr & 0xFF)

			self.instr( 0x75, 0xD2, cLow  ) # MOV direct,#data @ DMA1CFGL
			self.instr( 0x75, 0xD3, cHigh ) # MOV direct,#data @ DMA1CFGH

	def armDMAChannel(self, index):
		"""
		Arm a DMA channel (index in 0-4)
		"""

		# Get DMAARM state
		a = self.getRegister(0xD6) # MOV A,direct @ DMAARM

		# Set given flag
		a |= pow(2, index)

		# Update DMAARM state
		self.setRegister(0xD6, a) # MOV direct,#data @ DMAARM

		time.sleep(0.01)

	def disarmDMAChannel(self, index):
		"""
		Disarm a DMA channel (index in 0-4)
		"""

		# Get DMAARM state
		a = self.getRegister( 0xD6 )

		# Unset given flag
		flag = pow(2, index)
		a &= ~flag

		# Update DMAARM state
		self.setRegister( 0xD6, a )

	def isDMAIRQ(self, index):
		"""
		Check if DMA IRQ flag is set (index in 0-4)
		"""

		# Get DMAARM state
		a = self.getRegister( 0xD1 )

		# Lookup IRQ bit
		bit = pow(2, index)

		# Check if IRQ bit is set
		return ((a & bit) != 0)

	def clearDMAIRQ(self, index):
		"""
		Clear DMA IRQ flag (index in 0-4)
		"""

		# Get DMAIRQ state
		a = self.getRegister( 0xD1 )

		# Unset given flag
		flag = pow(2, index)
		a &= ~flag

		# Update DMAARM state
		self.setRegister( 0xD1, a )

	###############################################
	# Flash functions
	###############################################

	def setFlashWordOffset(self, address):
		"""
		Set the flash address offset in FADDRH:FADDRL
		"""

		# Split address in high/low order bytes
		cHigh = (address >> 8) & 0xFF
		cLow = (address & 0xFF)

		# Place in FADDRH:FADDRL
		self.writeXDATA( 0x6271, [cLow, cHigh])

	def isFlashFull(self):
		"""
		Check if the FULL bit is set in the flash register
		"""

		# Read flash status register
		a = self.readXDATA(0x6270, 1)
		return (a[0] & 0x40 != 0)

	def isFlashBusy(self):
		"""
		Check if the BUSY bit is set in the flash register
		"""

		# Read flash status register
		a = self.readXDATA(0x6270, 1)
		return (a[0] & 0x80 != 0)

	def isFlashAbort(self):
		"""
		Check if the ABORT bit is set in the flash register
		"""

		# Read flash status register
		a = self.readXDATA(0x6270, 1)
		return (a[0] & 0x20 != 0)

	def setFlashWrite(self):
		"""
		Set the WRITE bit in the flash control register
		"""

		# Set flash WRITE bit
		a = self.readXDATA(0x6270, 1)
		a[0] |= 0x02
		return self.writeXDATA(0x6270, a)

	def setFlashErase(self):
		"""
		Set the ERASE bit in the flash control register
		"""

		# Set flash ERASE bit
		a = self.readXDATA(0x6270, 1)
		a[0] |= 0x01
		return self.writeXDATA(0x6270, a)

	def writeCODE(self, offset, data, erase=False, blockSize=0x800, flashPageSize=0x800):
		"""
		Fully automated function for writing the Flash memory.

		WARNING: This requires DMA operations to be unpaused ( use: self.pauseDMA(False) )
		"""

		# Prepare DMA-0 for DEBUG -> RAM (using DBG_BW trigger)
		self.configDMAChannel( 0, 0x6260, 0x0000, 0x1F, tlen=blockSize, srcInc=0, dstInc=1, priority=1 )
		# Prepare DMA-1 for RAM -> FLASH (using the FLASH trigger)
		self.configDMAChannel( 1, 0x0000, 0x6273, 0x12, tlen=blockSize, srcInc=1, dstInc=0, priority=2, interrupt=True )

		# Split in 2048-byte chunks
		iOfs = 0
		while (iOfs < len(data)):

			# Get next page
			iLen = min( len(data) - iOfs, blockSize )

			# Update DMA configuration if we have less than blockSize data 
			if (iLen < blockSize):
				self.configDMAChannel( 0, 0x6260, 0x0000, 0x1F, tlen=iLen, srcInc=0, dstInc=1, priority=1 )
				self.configDMAChannel( 1, 0x0000, 0x6273, 0x12, tlen=iLen, srcInc=1, dstInc=0, priority=2, interrupt=True )

			# Upload to RAM through DMA-0
			self.armDMAChannel(0)
			self.brustWrite( data[iOfs:iLen] )

			# Calculate the page where this data belong to
			fAddr = offset + iOfs
			fPage = int( fAddr / flashPageSize )
			fOffset = fAddr % flashPageSize

			# Calculate FLASH address High/Low bytes
			cHigh = (fPage << 1) | ((fOffset << 8) & 0x01)
			cLow = fOffset & 0xFF

			# Set flash base address (FADDRL:FADDRH)
			self.writeXDATA( 0x6271, [cLow, cHigh] )

			# Check if we should erase page first
			if erase:
				# Set the erase bit
				self.setFlashErase()
				# Wait until flash is not busy any more
				while self.isFlashBusy():
					time.sleep(0.010)

			# Upload to FLASH through DMA-1
			self.armDMAChannel(1)
			self.setFlashWrite()

			# Wait until DMA-1 raises interrupt
			while not self.isDMAIRQ(1):
				time.sleep(0.010)

			# Clear DMA IRQ flag
			self.clearDMAIRQ(1)

			# Forward to next page
			iOfs += iLen


def renderDebugConfig(cfg):
	"""
	Visualize debug config
	"""
	if (cfg & 0x10) != 0:
		print " [X] SOFT_POWER_MODE"
	else:
		print " [ ] SOFT_POWER_MODE"
	if (cfg & 0x08) != 0:
		print " [X] TIMERS_OFF"
	else:
		print " [ ] TIMERS_OFF"
	if (cfg & 0x04) != 0:
		print " [X] DMA_PAUSE"
	else:
		print " [ ] DMA_PAUSE"
	if (cfg & 0x02) != 0:
		print " [X] TIMER_SUSPEND"
	else:
		print " [ ] TIMER_SUSPEND"

def renderDebugStatus(cfg):
	"""
	Visualize debug status
	"""
	if (cfg & 0x80) != 0:
		print " [X] CHIP_ERASE_BUSY"
	else:
		print " [ ] CHIP_ERASE_BUSY"
	if (cfg & 0x40) != 0:
		print " [X] PCON_IDLE"
	else:
		print " [ ] PCON_IDLE"
	if (cfg & 0x20) != 0:
		print " [X] CPU_HALTED"
	else:
		print " [ ] CPU_HALTED"
	if (cfg & 0x10) != 0:
		print " [X] PM_ACTIVE"
	else:
		print " [ ] PM_ACTIVE"
	if (cfg & 0x08) != 0:
		print " [X] HALT_STATUS"
	else:
		print " [ ] HALT_STATUS"
	if (cfg & 0x04) != 0:
		print " [X] DEBUG_LOCKED"
	else:
		print " [ ] DEBUG_LOCKED"
	if (cfg & 0x02) != 0:
		print " [X] OSCILLATOR_STABLE"
	else:
		print " [ ] OSCILLATOR_STABLE"
	if (cfg & 0x01) != 0:
		print " [X] STACK_OVERFLOW"
	else:
		print " [ ] STACK_OVERFLOW"
