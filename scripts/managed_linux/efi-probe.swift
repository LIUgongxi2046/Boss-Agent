import Foundation
import Virtualization

let directory = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
let systemDisk = directory.appendingPathComponent("system.raw")
let workspaceDisk = directory.appendingPathComponent("workspace.raw")
let installer = directory.appendingPathComponent("debian-13.7.0-amd64-netinst.iso")
let variableStoreURL = directory.appendingPathComponent("efi.nvram")
let configuration = VZVirtualMachineConfiguration()
configuration.cpuCount = 2
configuration.memorySize = 2 * 1024 * 1024 * 1024
configuration.platform = VZGenericPlatformConfiguration()
let bootLoader = VZEFIBootLoader()
if FileManager.default.fileExists(atPath: variableStoreURL.path) {
    bootLoader.variableStore = VZEFIVariableStore(url: variableStoreURL)
} else {
    bootLoader.variableStore = try VZEFIVariableStore(creatingVariableStoreAt: variableStoreURL)
}
if CommandLine.arguments.count > 2 && CommandLine.arguments[2] == "linux-probe" {
    let linux = VZLinuxBootLoader(kernelURL: directory.appendingPathComponent("install-vmlinuz"))
    linux.initialRamdiskURL = directory.appendingPathComponent("install-initrd.gz")
    linux.commandLine = "console=hvc0 DEBIAN_FRONTEND=text"
    configuration.bootLoader = linux
} else {
    configuration.bootLoader = bootLoader
}
let installAttachment = try VZDiskImageStorageDeviceAttachment(url: installer, readOnly: true)
let systemAttachment = try VZDiskImageStorageDeviceAttachment(url: systemDisk, readOnly: false)
let workspaceAttachment = try VZDiskImageStorageDeviceAttachment(url: workspaceDisk, readOnly: false)
configuration.storageDevices = [
    VZVirtioBlockDeviceConfiguration(attachment: installAttachment),
    VZVirtioBlockDeviceConfiguration(attachment: systemAttachment),
    VZVirtioBlockDeviceConfiguration(attachment: workspaceAttachment)
]
if CommandLine.arguments.count > 2 && CommandLine.arguments[2] == "efi-serial" {
    let bootAttachment = try VZDiskImageStorageDeviceAttachment(url: directory.appendingPathComponent("boot.cdr"), readOnly: true)
    configuration.storageDevices.insert(VZVirtioBlockDeviceConfiguration(attachment: bootAttachment), at: 0)
}
if CommandLine.arguments.count > 2 && CommandLine.arguments[2] == "installed" {
    configuration.storageDevices = [
        VZVirtioBlockDeviceConfiguration(attachment: systemAttachment),
        VZVirtioBlockDeviceConfiguration(attachment: workspaceAttachment)
    ]
}
let serial = VZVirtioConsoleDeviceSerialPortConfiguration()
serial.attachment = VZFileHandleSerialPortAttachment(fileHandleForReading: FileHandle.standardInput, fileHandleForWriting: FileHandle.standardOutput)
configuration.serialPorts = [serial]
try configuration.validate()
print("CONFIGURATION_VALIDATED network_devices=0 cpu=2 memory_bytes=2147483648")
fflush(stdout)
let machine = VZVirtualMachine(configuration: configuration)
machine.start { result in
    switch result {
    case .success:
        print("VM_STARTED")
    case .failure(let error):
        fputs("VM_START_FAILED: \(error)\n", stderr)
        exit(1)
    }
    fflush(stdout)
}
dispatchMain()
