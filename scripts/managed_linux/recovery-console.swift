import Foundation
import Virtualization

final class RecoveryDelegate: NSObject, VZVirtualMachineDelegate {
    func guestDidStop(_ virtualMachine: VZVirtualMachine) {
        print("RECOVERY_VM_STOPPED")
        fflush(stdout)
        exit(0)
    }

    func virtualMachine(_ virtualMachine: VZVirtualMachine, didStopWithError error: Error) {
        fputs("RECOVERY_VM_FAILED: \(error)\n", stderr)
        exit(1)
    }
}

guard CommandLine.arguments.count == 3 && CommandLine.arguments[2] == "rescue" else { fatalError("VM directory and rescue mode required") }
let directory = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
let configuration = VZVirtualMachineConfiguration()
configuration.cpuCount = 2
configuration.memorySize = 512 * 1024 * 1024
configuration.platform = VZGenericPlatformConfiguration()
let boot = VZLinuxBootLoader(kernelURL: directory.appendingPathComponent("install-vmlinuz"))
boot.initialRamdiskURL = directory.appendingPathComponent("install-initrd.gz")
boot.commandLine = "console=hvc0 DEBIAN_FRONTEND=text rescue/enable=true"
configuration.bootLoader = boot
let system = try VZDiskImageStorageDeviceAttachment(url: directory.appendingPathComponent("system.raw"), readOnly: false)
let workspace = try VZDiskImageStorageDeviceAttachment(url: directory.appendingPathComponent("workspace.raw"), readOnly: true)
let installer = try VZDiskImageStorageDeviceAttachment(url: directory.appendingPathComponent("debian-13.7.0-amd64-netinst.iso"), readOnly: true)
configuration.storageDevices = [VZVirtioBlockDeviceConfiguration(attachment: system), VZVirtioBlockDeviceConfiguration(attachment: workspace), VZVirtioBlockDeviceConfiguration(attachment: installer)]
let secretShare = VZVirtioFileSystemDeviceConfiguration(tag: "boss-recovery-secret")
secretShare.share = VZSingleDirectoryShare(directory: VZSharedDirectory(url: directory.appendingPathComponent("recovery-secrets-001", isDirectory: true), readOnly: true))
configuration.directorySharingDevices = [secretShare]
let serial = VZVirtioConsoleDeviceSerialPortConfiguration()
serial.attachment = VZFileHandleSerialPortAttachment(fileHandleForReading: FileHandle.standardInput, fileHandleForWriting: FileHandle.standardOutput)
configuration.serialPorts = [serial]
try configuration.validate()
let machine = VZVirtualMachine(configuration: configuration)
let delegate = RecoveryDelegate()
machine.delegate = delegate
signal(SIGTERM, SIG_IGN)
let shutdown = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
shutdown.setEventHandler {
    try! machine.requestStop()
}
shutdown.resume()
machine.start { result in
    switch result {
    case .success:
        print("RECOVERY_VM_STARTED")
    case .failure(let error):
        fputs("RECOVERY_VM_START_FAILED: \(error)\n", stderr)
        exit(1)
    }
    fflush(stdout)
}
dispatchMain()
