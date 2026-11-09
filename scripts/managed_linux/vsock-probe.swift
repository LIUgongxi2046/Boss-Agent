import CryptoKit
import Darwin
import Foundation
import Security
import Virtualization

func readMachineIdentifier(_ path: String) throws -> VZGenericMachineIdentifier {
    let descriptor = open(path, O_RDONLY | O_NOFOLLOW)
    guard descriptor >= 0 else { throw POSIXError(POSIXErrorCode(rawValue: errno)!) }
    let handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
    var info = stat()
    guard fstat(descriptor, &info) == 0, (info.st_mode & S_IFMT) == S_IFREG,
          info.st_uid == getuid(), (info.st_mode & 0o077) == 0 else {
        fatalError("machine identifier permissions invalid")
    }
    guard let data = try handle.readToEnd(), let identifier = VZGenericMachineIdentifier(dataRepresentation: data) else {
        fatalError("machine identifier invalid")
    }
    return identifier
}

if CommandLine.arguments.count == 3 && CommandLine.arguments[1] == "--init-identity" {
    let descriptor = open(CommandLine.arguments[2], O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0o600)
    guard descriptor >= 0 else { throw POSIXError(POSIXErrorCode(rawValue: errno)!) }
    let handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
    try handle.write(contentsOf: VZGenericMachineIdentifier().dataRepresentation)
    try handle.synchronize()
    print("VM_IDENTITY_INITIALIZED")
    exit(0)
}

if CommandLine.arguments.count == 3 && CommandLine.arguments[1] == "--check-identity" {
    let identifier = try readMachineIdentifier(CommandLine.arguments[2])
    print("VM_IDENTITY_SHA256 \(SHA256.hash(data: identifier.dataRepresentation).map { String(format: "%02x", $0) }.joined())")
    exit(0)
}

final class Listener: NSObject, VZVirtioSocketListenerDelegate {
    let key: SymmetricKey
    init(token: String) {
        key = SymmetricKey(data: Data(token.utf8))
    }

    func listener(_ listener: VZVirtioSocketListener, shouldAcceptNewConnection connection: VZVirtioSocketConnection, from socketDevice: VZVirtioSocketDevice) -> Bool {
        DispatchQueue.global().async {
            var challenge = [UInt8](repeating: 0, count: 32)
            guard SecRandomCopyBytes(kSecRandomDefault, challenge.count, &challenge) == errSecSuccess else {
                fatalError("random generation failed")
            }
            let handle = FileHandle(fileDescriptor: connection.fileDescriptor, closeOnDealloc: false)
            handle.write(Data(challenge))
            var received = Data()
            while received.count < 32 {
                guard let part = try! handle.read(upToCount: 32 - received.count), !part.isEmpty else {
                    print("VSOCK_INCOMPLETE")
                    return
                }
                received.append(part)
            }
            let accepted = HMAC<SHA256>.isValidAuthenticationCode(received, authenticating: Data(challenge), using: self.key)
            handle.write(Data((accepted ? "OK" : "DENIED").utf8))
            print(accepted ? "VSOCK_AUTHENTICATED" : "VSOCK_REJECTED")
            fflush(stdout)
            withExtendedLifetime(connection) {}
        }
        return true
    }
}

func relaySocketConnection(_ connection: VZVirtioSocketConnection, local: Int32, finish: @escaping () -> Void) {
    let guest = connection.fileDescriptor
    var enabled: Int32 = 1
    guard setsockopt(local, SOL_SOCKET, SO_NOSIGPIPE, &enabled, socklen_t(MemoryLayout<Int32>.size)) == 0,
          setsockopt(guest, SOL_SOCKET, SO_NOSIGPIPE, &enabled, socklen_t(MemoryLayout<Int32>.size)) == 0 else {
        Darwin.close(local)
        finish()
        return
    }
    let group = DispatchGroup()
    func forward(_ source: Int32, _ target: Int32) {
        var buffer = [UInt8](repeating: 0, count: 65536)
        while true {
            let count = Darwin.read(source, &buffer, buffer.count)
            if count == 0 {
                Darwin.shutdown(target, SHUT_WR)
                return
            }
            if count < 0 {
                Darwin.shutdown(source, SHUT_RDWR)
                Darwin.shutdown(target, SHUT_RDWR)
                return
            }
            var offset = 0
            while offset < count {
                let sent = buffer.withUnsafeBytes { bytes in
                    Darwin.send(target, bytes.baseAddress!.advanced(by: offset), count - offset, 0)
                }
                if sent <= 0 {
                    Darwin.shutdown(source, SHUT_RDWR)
                    Darwin.shutdown(target, SHUT_RDWR)
                    return
                }
                offset += sent
            }
        }
    }
    group.enter()
    DispatchQueue.global().async { forward(guest, local); group.leave() }
    group.enter()
    DispatchQueue.global().async { forward(local, guest); group.leave() }
    group.notify(queue: DispatchQueue.global()) {
        Darwin.close(local)
        finish()
        withExtendedLifetime(connection) {}
    }
}

final class RuntimeListener: NSObject, VZVirtioSocketListenerDelegate {
    let port: UInt16
    private let lock = NSLock()
    private var active = 0

    init(port: UInt16) {
        self.port = port
    }

    private func finish() {
        lock.lock()
        active -= 1
        lock.unlock()
    }

    func listener(_ listener: VZVirtioSocketListener, shouldAcceptNewConnection connection: VZVirtioSocketConnection, from socketDevice: VZVirtioSocketDevice) -> Bool {
        lock.lock()
        if active >= 16 {
            lock.unlock()
            return false
        }
        active += 1
        lock.unlock()
        DispatchQueue.global().async {
            let local = Darwin.socket(AF_INET, SOCK_STREAM, 0)
            guard local >= 0 else { self.finish(); return }
            var address = sockaddr_in()
            address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
            address.sin_family = sa_family_t(AF_INET)
            address.sin_port = self.port.bigEndian
            address.sin_addr = in_addr(s_addr: in_addr_t(0x7f000001).bigEndian)
            let connected = withUnsafePointer(to: &address) {
                $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                    Darwin.connect(local, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
                }
            }
            guard connected == 0 else {
                Darwin.close(local)
                self.finish()
                return
            }
            relaySocketConnection(connection, local: local) { self.finish() }
        }
        return true
    }
}

final class ControlListener {
    let descriptor: Int32
    let device: VZVirtioSocketDevice
    let guestPort: UInt32
    private let lock = NSLock()
    private var active = 0

    init(device: VZVirtioSocketDevice, port: UInt16, guestPort: UInt32) {
        self.device = device
        self.guestPort = guestPort
        descriptor = Darwin.socket(AF_INET, SOCK_STREAM, 0)
        guard descriptor >= 0 else { fatalError("control socket failed") }
        var address = sockaddr_in()
        address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        address.sin_family = sa_family_t(AF_INET)
        address.sin_port = port.bigEndian
        address.sin_addr = in_addr(s_addr: in_addr_t(0x7f000001).bigEndian)
        let bound = withUnsafePointer(to: &address) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                Darwin.bind(descriptor, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }
        guard bound == 0, Darwin.listen(descriptor, 16) == 0 else { fatalError("control listener failed") }
    }

    private func finish() {
        lock.lock()
        active -= 1
        lock.unlock()
    }

    func start() {
        DispatchQueue.global().async {
            while true {
                let local = Darwin.accept(self.descriptor, nil, nil)
                guard local >= 0 else { fatalError("control accept failed") }
                self.lock.lock()
                if self.active >= 16 {
                    self.lock.unlock()
                    Darwin.close(local)
                    continue
                }
                self.active += 1
                self.lock.unlock()
                Task { @MainActor in
                    self.device.__connect(toPort: self.guestPort) { connection, error in
                        guard let connection = connection, error == nil else {
                            fputs("VSOCK_CONTROL_CONNECT_FAILED port=\(self.guestPort) error=\(String(describing: error))\n", stderr)
                            fflush(stderr)
                            Darwin.close(local)
                            self.finish()
                            return
                        }
                        relaySocketConnection(connection, local: local) { self.finish() }
                    }
                }
            }
        }
    }
}

final class MachineDelegate: NSObject, VZVirtualMachineDelegate {
    func guestDidStop(_ virtualMachine: VZVirtualMachine) {
        print("VM_GUEST_STOPPED")
        fflush(stdout)
        exit(0)
    }

    func virtualMachine(_ virtualMachine: VZVirtualMachine, didStopWithError error: Error) {
        fputs("VM_STOP_FAILED: \(error)\n", stderr)
        exit(1)
    }
}

guard CommandLine.arguments.count == 3 else { fatalError("VM directory and share directory required") }
let directory = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
let shareDirectory = URL(fileURLWithPath: CommandLine.arguments[2], isDirectory: true)
let environment = ProcessInfo.processInfo.environment
struct WorkspaceForward: Decodable {
    let guest_port: UInt32
    let host_port: UInt16
}
let workspaceForwards: [WorkspaceForward]
let workspaceReverseForwards: [WorkspaceForward]
if let value = environment["BOSS_VSOCK_WORKSPACE_PORTS"] {
    workspaceForwards = try JSONDecoder().decode([WorkspaceForward].self, from: Data(value.utf8))
    guard let runtimeValue = environment["BOSS_VSOCK_FORWARD_PORT"], let runtimePort = UInt16(runtimeValue), runtimePort > 0,
          let controlValue = environment["BOSS_VSOCK_CONTROL_PORT"], let controlPort = UInt16(controlValue), controlPort > 0,
          runtimePort != controlPort, !workspaceForwards.isEmpty, workspaceForwards.count <= 16,
          workspaceForwards.allSatisfy({ $0.guest_port > 1025 && $0.host_port > 0 }),
          workspaceForwards.allSatisfy({ $0.host_port != runtimePort && $0.host_port != controlPort }),
          Set(workspaceForwards.map(\.guest_port)).count == workspaceForwards.count,
          Set(workspaceForwards.map(\.host_port)).count == workspaceForwards.count else {
        fatalError("workspace forwarding ports invalid")
    }
} else {
    workspaceForwards = []
}
if let value = environment["BOSS_VSOCK_WORKSPACE_REVERSE_PORTS"] {
    workspaceReverseForwards = try JSONDecoder().decode([WorkspaceForward].self, from: Data(value.utf8))
    guard let runtimeValue = environment["BOSS_VSOCK_FORWARD_PORT"], let runtimePort = UInt16(runtimeValue), runtimePort > 0,
          let controlValue = environment["BOSS_VSOCK_CONTROL_PORT"], let controlPort = UInt16(controlValue), controlPort > 0,
          runtimePort != controlPort, !workspaceReverseForwards.isEmpty, workspaceReverseForwards.count <= 16,
          workspaceReverseForwards.allSatisfy({ $0.guest_port > 1025 && $0.host_port > 0 }),
          workspaceReverseForwards.allSatisfy({ $0.host_port != runtimePort && $0.host_port != controlPort }),
          Set(workspaceReverseForwards.map(\.guest_port)).count == workspaceReverseForwards.count,
          Set(workspaceReverseForwards.map(\.host_port)).count == workspaceReverseForwards.count,
          Set(workspaceReverseForwards.map(\.guest_port)).isDisjoint(with: Set(workspaceForwards.map(\.guest_port))),
          Set(workspaceReverseForwards.map(\.host_port)).isDisjoint(with: Set(workspaceForwards.map(\.host_port))) else {
        fatalError("workspace reverse forwarding ports invalid")
    }
} else {
    workspaceReverseForwards = []
}
let delegate: NSObject & VZVirtioSocketListenerDelegate
if let value = environment["BOSS_VSOCK_FORWARD_PORT"] {
    guard let port = UInt16(value), port > 0 else { fatalError("runtime port invalid") }
    delegate = RuntimeListener(port: port)
} else {
    guard let token = environment["BOSS_VSOCK_PROBE_TOKEN"], token.utf8.count >= 32 else {
        fatalError("probe token required")
    }
    delegate = Listener(token: token)
}
let configuration = VZVirtualMachineConfiguration()
configuration.cpuCount = 2
configuration.memorySize = 2 * 1024 * 1024 * 1024
let platform = VZGenericPlatformConfiguration()
platform.machineIdentifier = try readMachineIdentifier(directory.appendingPathComponent("machine-identity").path)
configuration.platform = platform
let boot = VZEFIBootLoader()
boot.variableStore = VZEFIVariableStore(url: directory.appendingPathComponent("efi.nvram"))
configuration.bootLoader = boot
let system = try VZDiskImageStorageDeviceAttachment(url: directory.appendingPathComponent("system.raw"), readOnly: false)
let workspace = try VZDiskImageStorageDeviceAttachment(url: directory.appendingPathComponent("workspace.raw"), readOnly: false)
configuration.storageDevices = [VZVirtioBlockDeviceConfiguration(attachment: system), VZVirtioBlockDeviceConfiguration(attachment: workspace)]
configuration.socketDevices = [VZVirtioSocketDeviceConfiguration()]
let share = VZVirtioFileSystemDeviceConfiguration(tag: "boss-probe")
share.share = VZSingleDirectoryShare(directory: VZSharedDirectory(url: shareDirectory, readOnly: true))
configuration.directorySharingDevices = [share]
if let dependencies = environment["BOSS_VSOCK_DEPENDENCIES"] {
    let dependencyShare = VZVirtioFileSystemDeviceConfiguration(tag: "boss-dependencies")
    dependencyShare.share = VZSingleDirectoryShare(directory: VZSharedDirectory(url: URL(fileURLWithPath: dependencies, isDirectory: true), readOnly: true))
    configuration.directorySharingDevices.append(dependencyShare)
}
if let engine = environment["BOSS_VSOCK_ENGINE"] {
    let engineShare = VZVirtioFileSystemDeviceConfiguration(tag: "boss-engine")
    engineShare.share = VZSingleDirectoryShare(directory: VZSharedDirectory(url: URL(fileURLWithPath: engine, isDirectory: true), readOnly: true))
    configuration.directorySharingDevices.append(engineShare)
}
if environment["BOSS_VSOCK_FORWARD_PORT"] == nil || environment["BOSS_VSOCK_SERIAL"] == "1" {
    let serial = VZVirtioConsoleDeviceSerialPortConfiguration()
    serial.attachment = VZFileHandleSerialPortAttachment(fileHandleForReading: FileHandle.standardInput, fileHandleForWriting: FileHandle.standardOutput)
    configuration.serialPorts = [serial]
}
try configuration.validate()
let machine = VZVirtualMachine(configuration: configuration)
let machineDelegate = MachineDelegate()
machine.delegate = machineDelegate
signal(SIGTERM, SIG_IGN)
let shutdownSignal = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
shutdownSignal.setEventHandler {
    try! machine.requestStop()
}
shutdownSignal.resume()
let listener = VZVirtioSocketListener()
listener.delegate = delegate
var controlListener: ControlListener?
var workspaceReverseListeners: [ControlListener] = []
var workspaceListeners: [RuntimeListener] = []
var workspaceSockets: [VZVirtioSocketListener] = []
machine.start { result in
    switch result {
    case .success:
        let device = machine.socketDevices[0] as! VZVirtioSocketDevice
        device.setSocketListener(listener, forPort: 1024)
        for forward in workspaceForwards {
            let workspaceListener = VZVirtioSocketListener()
            let workspaceDelegate = RuntimeListener(port: forward.host_port)
            workspaceListener.delegate = workspaceDelegate
            workspaceListeners.append(workspaceDelegate)
            workspaceSockets.append(workspaceListener)
            device.setSocketListener(workspaceListener, forPort: forward.guest_port)
        }
        if let value = environment["BOSS_VSOCK_CONTROL_PORT"] {
            guard environment["BOSS_VSOCK_FORWARD_PORT"] != nil, let port = UInt16(value), port > 0 else {
                fatalError("control port invalid")
            }
            controlListener = ControlListener(device: device, port: port, guestPort: 1025)
            controlListener!.start()
            print("CONTROL_LISTENING")
        }
        for forward in workspaceReverseForwards {
            let reverseListener = ControlListener(device: device, port: forward.host_port, guestPort: forward.guest_port)
            workspaceReverseListeners.append(reverseListener)
            reverseListener.start()
        }
        print("VSOCK_LISTENING")
    case .failure(let error):
        fputs("VM_START_FAILED: \(error)\n", stderr)
        exit(1)
    }
    fflush(stdout)
}
dispatchMain()
