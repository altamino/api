from re import match
from packaging.version import Version

class UserAgentProcessor:
    """
    Processor that validates "User-Agent".
    Made because why not.

    Possible User-Agents:
    - android amino app header
    - ios amino app header
    - browser header

    Maybe there will be more User-Agents.
    """

    browser_pattern = r"Mozilla\/(\S+) (\(.*\))(?: (.*)|$)"
    dalvik_pattern = r"Dalvik\/(\S+) \(Linux; U; Android (\S+); .*; .*\)"
    apple_pattern = r"Apple (.*) (iOS|iPadOS|tvOS) v(.*) \S+"
    apple_devices = [
        # simulators
        'i386', 'x86_64', 'arm64', 'arm64e', 
        # iphones
        'iPhone8,1', 'iPhone8,2', 'iPhone8,4', 'iPhone9,1', 'iPhone9,2', 'iPhone9,3', 'iPhone9,4', 'iPhone10,1', 'iPhone10,2', 'iPhone10,3', 'iPhone10,4', 'iPhone10,5', 'iPhone10,6', 'iPhone11,2', 'iPhone11,4', 'iPhone11,6', 'iPhone11,8', 'iPhone12,1', 'iPhone12,3', 'iPhone12,5', 'iPhone12,8', 'iPhone13,1', 'iPhone13,2', 'iPhone13,3', 'iPhone13,4', 'iPhone14,2', 'iPhone14,3', 'iPhone14,4', 'iPhone14,5', 'iPhone14,6', 'iPhone14,7', 'iPhone14,8', 'iPhone15,2', 'iPhone15,3', 'iPhone15,4', 'iPhone15,5', 'iPhone16,1', 'iPhone16,2',
        # ipod
        'iPod9,1',
        # ipads
        'iPad5,1', 'iPad5,2', 'iPad5,3', 'iPad5,4', 'iPad6,3', 'iPad6,4', 'iPad6,7', 'iPad6,8', 'iPad6,11', 'iPad6,12', 'iPad7,1', 'iPad7,2', 'iPad7,3', 'iPad7,4', 'iPad7,5', 'iPad7,6', 'iPad7,11', 'iPad7,12', 'iPad8,1', 'iPad8,2', 'iPad8,3', 'iPad8,4', 'iPad8,5', 'iPad8,6', 'iPad8,7', 'iPad8,8', 'iPad8,9', 'iPad8,10', 'iPad8,11', 'iPad8,12', 'iPad11,1', 'iPad11,2', 'iPad11,3', 'iPad11,4', 'iPad11,6', 'iPad11,7', 'iPad12,1', 'iPad12,2', 'iPad14,1', 'iPad14,2', 'iPad13,1', 'iPad13,2', 'iPad13,4', 'iPad13,5', 'iPad13,6', 'iPad13,7', 'iPad13,8', 'iPad13,9', 'iPad13,10', 'iPad13,11', 'iPad13,16', 'iPad13,17', 'iPad13,18', 'iPad13,19', 'iPad14,3', 'iPad14,4', 'iPad14,5', 'iPad14,6', 'iPad14,8', 'iPad14,9', 'iPad14,10', 'iPad14,11', 'iPad16,3', 'iPad16,4', 'iPad16,5', 'iPad16,6'
    ]

    @staticmethod
    def Validate(user_agent: str):
        """
        True - user_agent is valid
        False - user_agent is NOT valid
        """
        browser = match(UserAgentProcessor.browser_pattern, user_agent)
        dalvik = match(UserAgentProcessor.dalvik_pattern, user_agent)
        apple = match(UserAgentProcessor.apple_pattern, user_agent)

        if dalvik:
            dalvik_version, android_version = dalvik.groups()
            if Version(dalvik_version) < Version("2"):
                return False
            elif Version(android_version) < Version("6"):
                return False
            
            return True
        elif apple:
            apple_device, os_type, os_version = apple.groups()
            if apple_device not in UserAgentProcessor.apple_devices:
                return False 
            elif Version(os_version) < Version("14.0"):
                return False
            
            return True
        elif browser:
            mozilla_version, device_info, additional_browser_info = browser.groups()
            if Version(mozilla_version) < Version("5"):
                return False

            return True
        
        return False