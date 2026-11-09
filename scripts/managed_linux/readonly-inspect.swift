import Foundation
import Virtualization

final class InspectionDelegate: NSObject, VZVirtualMachineDelegate {
    func guestDidStop(_ virtualMachine: VZVirtualMachine) {
        print("INSPECTION_VM_STOPPED")
        fflush(stdout)
        exit(0)
    }

    func virtualMachine(_ virtualMachine: VZVirtualMachine, didStopWithError error: Error) {
        fputs("INSPECTION_VM_FAILED: \(error)\n", stderr)
        exit(1)
    }
}

let arguments = CommandLine.arguments
guard arguments.count == 3 || arguments.count == 4 && arguments[3] == "install-python" || arguments.count == 6 && ["guest-setup", "guest-workspace-setup"].contains(arguments[3]) else { fatalError("VM directory and share directory required") }
let installPython = arguments.count > 3
let writableWorkspace = arguments.count == 6 && arguments[3] == "guest-workspace-setup"
let directory = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
let shared = URL(fileURLWithPath: CommandLine.arguments[2], isDirectory: true)
let configuration = VZVirtualMachineConfiguration()
configuration.cpuCount = 2
configuration.memorySize = 512 * 1024 * 1024
configuration.platform = VZGenericPlatformConfiguration()
let boot = VZEFIBootLoader()
boot.variableStore = VZEFIVariableStore(url: directory.appendingPathComponent("efi.nvram"))
configuration.bootLoader = boot
let system = try VZDiskImageStorageDeviceAttachment(url: directory.appendingPathComponent("system.raw"), readOnly: !installPython)
let workspace = try VZDiskImageStorageDeviceAttachment(url: directory.appendingPathComponent("workspace.raw"), readOnly: !writableWorkspace)
configuration.storageDevices = [VZVirtioBlockDeviceConfiguration(attachment: system), VZVirtioBlockDeviceConfiguration(attachment: workspace)]
let share = VZVirtioFileSystemDeviceConfiguration(tag: "boss-probe")
share.share = VZSingleDirectoryShare(directory: VZSharedDirectory(url: shared, readOnly: true))
configuration.directorySharingDevices = [share]
if arguments.count == 6 {
    let runtime = VZVirtioFileSystemDeviceConfiguration(tag: "boss-guest-runtime")
    runtime.share = VZSingleDirectoryShare(directory: VZSharedDirectory(url: URL(fileURLWithPath: arguments[4], isDirectory: true), readOnly: true))
    let checks = VZVirtioFileSystemDeviceConfiguration(tag: "boss-checks")
    checks.share = VZSingleDirectoryShare(directory: VZSharedDirectory(url: URL(fileURLWithPath: arguments[5], isDirectory: true), readOnly: true))
    configuration.directorySharingDevices.append(runtime)
    configuration.directorySharingDevices.append(checks)
}
let serial = VZVirtioConsoleDeviceSerialPortConfiguration()
serial.attachment = VZFileHandleSerialPortAttachment(fileHandleForReading: FileHandle.standardInput, fileHandleForWriting: FileHandle.standardOutput)
configuration.serialPorts = [serial]
try configuration.validate()
let machine = VZVirtualMachine(configuration: configuration)
let delegate = InspectionDelegate()
machine.delegate = delegate
signal(SIGTERM, SIG_IGN)
let shutdown = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
shutdown.setEventHandler { try! machine.requestStop() }
shutdown.resume()
machine.start { result in
    switch result {
    case .success:
        print("READONLY_VM_STARTED")
    case .failure(let error):
        fputs("READONLY_VM_FAILED: \(error)\n", stderr)
        exit(1)
    }
    fflush(stdout)
}
dispatchMain()
