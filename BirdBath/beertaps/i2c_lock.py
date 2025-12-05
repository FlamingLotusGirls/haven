#!/usr/bin/env python3
"""
I2C Device Locking Module

Provides file-based locking for I2C devices (specifically ADS1115 ADCs) to prevent
multiple processes from accessing the same device simultaneously, which causes
erroneous readings due to interleaved I2C transactions.

Usage:
    from i2c_lock import I2CLock, I2CDeviceInUseError
    
    # As a context manager (recommended):
    with I2CLock(0x48) as lock:
        # Access I2C device at address 0x48
        ...
    
    # Or manually:
    lock = I2CLock(0x48)
    lock.acquire()  # Raises I2CDeviceInUseError if already locked
    try:
        # Access I2C device
        ...
    finally:
        lock.release()
"""

import os
import fcntl
import errno


class I2CDeviceInUseError(Exception):
    """Raised when an I2C device is already in use by another process"""
    pass


class I2CLock:
    """
    File-based lock for I2C device access.
    
    Uses flock() for automatic cleanup on process exit/crash.
    Lock files are stored in /var/lock/ with format: i2c-ads1115-0xXX.lock
    """
    
    LOCK_DIR = "/var/lock"
    
    def __init__(self, address, blocking=False):
        """
        Initialize lock for an I2C address.
        
        Args:
            address: I2C address as int (0x48) or string ("0x48")
            blocking: If True, wait for lock. If False, fail immediately if locked.
        """
        # Normalize address to integer
        if isinstance(address, str):
            self.address = int(address, 16)
        else:
            self.address = address
        
        self.blocking = blocking
        self.lock_file = os.path.join(
            self.LOCK_DIR, 
            f"i2c-ads1115-{hex(self.address)}.lock"
        )
        self.fd = None
        self._locked = False
    
    def _get_lock_holder_info(self):
        """
        Try to read info about the process holding the lock.
        Returns a human-readable string describing the lock holder.
        """
        try:
            with open(self.lock_file, 'r') as f:
                content = f.read().strip()
                if content:
                    # Parse PID:command format
                    parts = content.split(':', 1)
                    if len(parts) == 2:
                        pid, cmd = parts
                        # Verify the process is still running
                        try:
                            os.kill(int(pid), 0)  # Signal 0 = check existence
                            return f"PID {pid} ({cmd})"
                        except OSError:
                            return f"PID {pid} (process may have exited)"
                    return content
        except (IOError, OSError):
            pass
        return "unknown process"
    
    def _write_lock_info(self):
        """Write info about this process to the lock file."""
        try:
            pid = os.getpid()
            # Get command name from /proc
            try:
                with open(f'/proc/{pid}/comm', 'r') as f:
                    cmd = f.read().strip()
            except IOError:
                cmd = "unknown"
            
            # Write to lock file (we already have the lock, so this is safe)
            os.lseek(self.fd, 0, os.SEEK_SET)
            os.ftruncate(self.fd, 0)
            os.write(self.fd, f"{pid}:{cmd}\n".encode())
        except (IOError, OSError):
            pass  # Non-critical, locking still works
    
    def acquire(self):
        """
        Acquire the lock.
        
        Raises:
            I2CDeviceInUseError: If device is locked and blocking=False
            OSError: If lock file cannot be created (permissions, etc.)
        """
        if self._locked:
            return  # Already locked by us
        
        try:
            # Create lock file (or open existing)
            self.fd = os.open(
                self.lock_file, 
                os.O_RDWR | os.O_CREAT,
                0o644
            )
        except OSError as e:
            if e.errno == errno.EACCES:
                raise OSError(
                    f"Cannot create lock file {self.lock_file}. "
                    f"Check permissions on {self.LOCK_DIR} or run with sudo."
                ) from e
            raise
        
        try:
            # Try to acquire exclusive lock
            flags = fcntl.LOCK_EX
            if not self.blocking:
                flags |= fcntl.LOCK_NB
            
            fcntl.flock(self.fd, flags)
            
        except OSError as e:
            if e.errno in (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK):
                # Lock is held by another process
                os.close(self.fd)
                self.fd = None
                
                holder = self._get_lock_holder_info()
                raise I2CDeviceInUseError(
                    f"\n"
                    f"************************************************************\n"
                    f"*  ERROR: I2C DEVICE IN USE                                *\n"
                    f"************************************************************\n"
                    f"!\n"
                    f"!  ADS1115 ADC device at address {hex(self.address)} in use by another process.\n"
                    f"!  Currently held by: {holder}\n"
                    f"!\n"
                    f"!  Stop that process first, e.g.:\n"
                    f"!    sudo systemctl stop adc-reader-*.service\n"
                    f"!\n"
                    f"************************************************************\n"
                ) from None
            raise
        
        self._locked = True
        self._write_lock_info()
    
    def release(self):
        """Release the lock."""
        if self.fd is not None:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None
        self._locked = False
    
    def __enter__(self):
        """Context manager entry."""
        self.acquire()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.release()
        return False  # Don't suppress exceptions
    
    def __del__(self):
        """Destructor - ensure lock is released."""
        self.release()


class MultiI2CLock:
    """
    Lock multiple I2C addresses at once.
    
    Usage:
        with MultiI2CLock([0x48, 0x49, 0x4a]) as locks:
            # All three devices are now locked
            ...
    """
    
    def __init__(self, addresses, blocking=False):
        """
        Initialize locks for multiple I2C addresses.
        
        Args:
            addresses: List of I2C addresses
            blocking: If True, wait for locks. If False, fail immediately.
        """
        self.locks = [I2CLock(addr, blocking) for addr in addresses]
        self._acquired = []
    
    def acquire(self):
        """Acquire all locks. If any fails, release those already acquired."""
        try:
            for lock in self.locks:
                lock.acquire()
                self._acquired.append(lock)
        except Exception:
            # Release any locks we acquired
            for lock in self._acquired:
                lock.release()
            self._acquired = []
            raise
    
    def release(self):
        """Release all locks."""
        for lock in self._acquired:
            lock.release()
        self._acquired = []
    
    def __enter__(self):
        self.acquire()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
        return False


# Convenience function for simple use cases
def check_i2c_available(address):
    """
    Check if an I2C address is available (not locked).
    
    Args:
        address: I2C address to check
        
    Returns:
        True if available, False if in use
    """
    try:
        lock = I2CLock(address, blocking=False)
        lock.acquire()
        lock.release()
        return True
    except I2CDeviceInUseError:
        return False


if __name__ == "__main__":
    # Quick test
    import sys
    
    if len(sys.argv) > 1:
        addr = int(sys.argv[1], 16) if sys.argv[1].startswith('0x') else int(sys.argv[1])
    else:
        addr = 0x48
    
    print(f"Testing I2C lock for address {hex(addr)}...")
    
    try:
        with I2CLock(addr) as lock:
            print(f"✓ Successfully acquired lock for {hex(addr)}")
            print("  Lock will be held for 10 seconds (press Ctrl+C to release early)")
            import time
            time.sleep(10)
    except I2CDeviceInUseError as e:
        print(str(e))
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n  Lock released early")
    
    print("✓ Lock released")
