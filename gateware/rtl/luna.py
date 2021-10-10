#!/usr/bin/env python3
#
# This file is part of LUNA.
#
# Copyright (c) 2020 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

import sys
import logging
import os.path

from nmigen import Elaboratable, Module, ResetSignal, Signal
from nmigen.hdl.rec import Record
from nmigen_soc import wishbone

from lambdasoc.periph import Peripheral
from lambdasoc.periph.serial import AsyncSerialPeripheral
from lambdasoc.periph.timer import TimerPeripheral

from luna.gateware.soc import SimpleSoC

from luna.gateware.usb.usb2.device import USBDevice, USBDeviceController
from luna.gateware.architecture.car import PHYResetController
from luna.gateware.usb.usb2.interfaces.eptri import SetupFIFOInterface, InFIFOInterface, OutFIFOInterface

from nmigen.hdl.rec import Direction
#from nmigen.hdl.rec import DIR_FANIN, DIR_FANOUT, DIR_NONE

CLOCK_FREQUENCIES_MHZ = {
    'sync': 60
}


class LunaEpTri(Elaboratable):
    """ Simple SoC for hosting TinyUSB. """

    USB_CORE_ADDRESS = 0x0000_0000
    USB_SETUP_ADDRESS = 0x0000_1000
    USB_IN_ADDRESS = 0x0000_2000
    USB_OUT_ADDRESS = 0x0000_3000

    def __init__(self):

        # Create a stand-in for our ULPI.
        self.ulpi = Record(
            [
                ('data', [('i', 8, Direction.FANIN),
                 ('o', 8, Direction.FANOUT), ('oe', 1, Direction.FANOUT)]),
                ('clk', [('o', 1, Direction.FANOUT)]),
                ('stp', 1, Direction.FANOUT),
                ('nxt', [('i', 1, Direction.FANIN)]),
                ('dir', [('i', 1, Direction.FANIN)]),
                ('rst', 1, Direction.FANOUT)
            ]
        )

        self.bus_decoder = wishbone.Decoder(
            addr_width=30, data_width=32, granularity=8)
        self.memory_map = self.bus_decoder.bus.memory_map
        self.bus = self.bus_decoder.bus

        self.usb_holdoff = Signal()
 
        # ... a core USB controller ...
        self.usb_device_controller = USBDeviceController()
        self.add_peripheral(self.usb_device_controller, addr=self.USB_CORE_ADDRESS)

        # ... our eptri peripherals.
        self.usb_setup = SetupFIFOInterface()
        self.add_peripheral(self.usb_setup, addr=self.USB_SETUP_ADDRESS)

        self.usb_in_ep = InFIFOInterface()
        self.add_peripheral(self.usb_in_ep, addr=self.USB_IN_ADDRESS)

        self.usb_out_ep = OutFIFOInterface()
        self.add_peripheral(self.usb_out_ep, addr=self.USB_OUT_ADDRESS)

    def add_peripheral(self, p, **kwargs):
        """ Adds a peripheral to the SoC.

        For now, this is identical to adding a peripheral to the SoC's wishbone bus.
        For convenience, returns the peripheral provided.
        """

        # Add the peripheral to our bus...
        interface = getattr(p, 'bus')
        self.bus_decoder.add(interface, **kwargs)

        # ... add its IRQs to the IRQ controller...
        try:
            irq_line = getattr(p, 'irq')
            setattr(self, irq_line.name, irq_line)
        except (AttributeError, NotImplementedError):

            # If the object has no associated IRQs, continue anyway.
            # This allows us to add devices with only Wishbone interfaces to our SoC.
            pass

    def elaborate(self, platform):
        m = Module()
        m.submodules.bus_decoder = self.bus_decoder

        # Generate our domain clocks/resets.
        #m.submodules.car = platform.clock_domain_generator(clock_frequencies=CLOCK_FREQUENCIES_MHZ)

        # Create our USB device.
        m.submodules.usb_controller = self.usb_device_controller
        m.submodules.usb = usb = USBDevice(bus=self.ulpi)

        
        m.submodules.usb_reset = controller = PHYResetController(clock_frequency=60e6, reset_length=10e-3, stop_length=2e-4, power_on_reset=True)
        m.d.comb += [
            ResetSignal("usb")  .eq(controller.phy_reset),
            self.usb_holdoff    .eq(controller.phy_stop)
        ]


        m.d.comb += usb.full_speed_only.eq(0)

        # Connect up our device controller.
        m.d.comb += self.usb_device_controller.attach(usb)

        # Add our eptri endpoint handlers.
        usb.add_endpoint(self.usb_setup)
        usb.add_endpoint(self.usb_in_ep)
        usb.add_endpoint(self.usb_out_ep)

        return m
