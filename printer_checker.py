#!/usr/bin/env python3
"""
打印机在线状态检测模块
支持多种协议：IPP, Socket, BJNP, LPD, USB 等
"""

import subprocess
import logging
import socket
import tempfile
import os
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def check_ipptool_available():
    """检查 ipptool 命令是否可用"""
    try:
        result = subprocess.run(
            ['which', 'ipptool'],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


IPPTOOL_AVAILABLE = check_ipptool_available()


def check_printer_online(printer_uri, timeout=5):
    """
    检查打印机是否在线（支持多种协议）
    
    根据打印机 URI 的协议类型，使用对应的方式进行探测：
    - ipp://, ipps:// -> 使用 ipptool 发送 IPP 请求
    - socket:// -> TCP 连接 9100 端口
    - bjnp:// -> TCP 连接 8611 端口 (Canon)
    - lpd:// -> TCP 连接 515 端口
    - usb:// -> 返回 True (无法远程探测)
    - 其他网络打印机 -> 尝试提取 IP 并探测常见端口
    
    Args:
        printer_uri: 打印机 URI (如 ipp://192.168.1.16:631/ipp/print)
        timeout: 超时时间（秒），默认 5 秒
    
    Returns:
        dict: {
            'online': True/False,
            'method': 'ipp'/'socket'/'bjnp'/'lpd'/'usb'/'unknown',
            'message': '详细信息'
        }
    """
    try:
        parsed = urlparse(printer_uri)
        scheme = parsed.scheme.lower()
        hostname = parsed.hostname
        port = parsed.port
        
        # USB 打印机 - 无法远程探测，假设在线
        if scheme == 'usb' or not hostname:
            return {
                'online': True,
                'method': 'usb',
                'message': 'USB 打印机，无法远程探测'
            }
        
        # 根据协议类型选择探测方式
        if scheme in ('ipp', 'ipps'):
            return _check_ipp_printer_quick(printer_uri, timeout)  # 使用快速检测
        elif scheme == 'socket':
            # Raw Socket 打印，默认端口 9100
            port = port or 9100
            return _check_tcp_port(hostname, port, timeout)
        elif scheme == 'bjnp':
            # Canon BJNP 协议，端口 8611 或 8612
            return _check_bjnp_printer(hostname, port, timeout)
        elif scheme == 'lpd':
            # LPD 协议，端口 515
            port = port or 515
            return _check_tcp_port(hostname, port, timeout)
        elif scheme in ('http', 'https'):
            # HTTP/HTTPS 协议，检查对应端口
            port = port or (443 if scheme == 'https' else 80)
            return _check_tcp_port(hostname, port, timeout)
        else:
            # 未知协议，尝试提取 IP 并探测常见打印端口
            logger.debug(f"未知协议 '{scheme}'，尝试通用探测：{printer_uri}")
            return _check_generic_printer(hostname, port, timeout)
            
    except Exception as e:
        logger.error(f"检查打印机在线状态失败：{printer_uri}, 错误：{e}")
        return {
            'online': False,
            'method': 'unknown',
            'message': f'探测异常：{str(e)}'
        }


def _check_ipp_printer_quick(printer_uri, timeout=3):
    """
    使用 ipptool 快速检查 IPP 打印机是否在线（简化版，只请求 printer-state）
    
    使用自定义的简化测试文件，只请求 printer-state 属性，
    大幅减少响应数据量和处理时间（从 3-4 秒降低到 0.3 秒）
    
    Args:
        printer_uri: 打印机 URI
        timeout: 超时时间（秒），默认 3 秒
    
    Returns:
        dict: {'online': True/False, 'method': 'ipp', 'message': str}
    """
    if not IPPTOOL_AVAILABLE:
        return {
            'online': False,
            'method': 'ipp',
            'message': 'ipptool 不可用'
        }

    try:
        # 创建简化的测试文件（只请求 printer-state）
        test_content = """{
    NAME "Quick-Online-Check"
    OPERATION Get-Printer-Attributes
    GROUP operation
    ATTR charset attributes-charset utf-8
    ATTR language attributes-natural-language en
    ATTR uri printer-uri """ + printer_uri + """
    ATTR keyword requested-attributes printer-state
}
"""
        # 写入临时文件
        fd, test_file = tempfile.mkstemp(suffix='.test')
        try:
            os.write(fd, test_content.encode('utf-8'))
            os.close(fd)
            
            # 执行简化的 ipptool 检测
            cmd = ['ipptool', '-t', '-T', str(timeout), printer_uri, test_file]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout + 2
            )
            
            # 检查是否成功
            if '[PASS]' in result.stdout:
                return {
                    'online': True,
                    'method': 'ipp',
                    'message': 'IPP 快速检测通过'
                }
            
            # 检查错误
            error_msg = result.stderr.strip() if result.stderr else '无响应'
            if 'timeout' in error_msg.lower() or 'timed out' in result.stdout.lower():
                return {
                    'online': False,
                    'method': 'ipp',
                    'message': 'IPP 连接超时'
                }
            
            return {
                'online': False,
                'method': 'ipp',
                'message': 'IPP 快速检测失败'
            }

        finally:
            # 清理临时文件
            try:
                os.unlink(test_file)
            except OSError:
                pass  # 忽略文件删除失败

    except subprocess.TimeoutExpired:
        return {
            'online': False,
            'method': 'ipp',
            'message': 'IPP 连接超时'
        }
    except Exception as e:
        return {
            'online': False,
            'method': 'ipp',
            'message': f'IPP 检测异常：{str(e)}'
        }


def _check_tcp_port(hostname, port, timeout=5):
    """
    检查 TCP 端口是否开放
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((hostname, port))
        sock.close()

        if result == 0:
            return {
                'online': True,
                'method': 'socket',
                'message': f'端口 {port} 开放'
            }
        else:
            return {
                'online': False,
                'method': 'socket',
                'message': f'端口 {port} 无法连接'
            }

    except socket.timeout:
        return {
            'online': False,
            'method': 'socket',
            'message': f'连接 {hostname}:{port} 超时'
        }
    except Exception as e:
        return {
            'online': False,
            'method': 'socket',
            'message': f'端口探测异常：{str(e)}'
        }


def _check_bjnp_printer(hostname, port=None, timeout=5):
    """
    检查 Canon BJNP 打印机是否在线
    BJNP 协议使用端口 8611 或 8612
    """
    # BJNP 端口优先级：8611 > 8612
    ports_to_try = []
    if port:
        ports_to_try.append(port)
    else:
        ports_to_try = [8611, 8612]

    for try_port in ports_to_try:
        result = _check_tcp_port(hostname, try_port, timeout)
        if result['online']:
            result['method'] = 'bjnp'
            result['message'] = f'BJNP 端口 {try_port} 开放'
            return result

    return {
        'online': False,
        'method': 'bjnp',
        'message': 'BJNP 端口 8611/8612 均无法连接'
    }


def _check_generic_printer(hostname, port, timeout=5):
    """
    通用打印机探测：尝试常见打印端口
    """
    # 常见打印端口列表
    common_ports = [
        9100,  # HP JetDirect / Raw Socket
        631,   # IPP
        515,   # LPD
        8611,  # BJNP
        8612,  # BJNP
    ]
    
    # 如果指定了端口，优先尝试
    if port and port not in common_ports:
        common_ports.insert(0, port)
    
    for try_port in common_ports:
        result = _check_tcp_port(hostname, try_port, timeout)
        if result['online']:
            return {
                'online': True,
                'method': 'generic',
                'message': f'端口 {try_port} 开放'
            }
    
    return {
        'online': False,
        'method': 'generic',
        'message': '所有常见打印端口均无法连接'
    }


if __name__ == '__main__':
    # 测试代码
    logging.basicConfig(level=logging.DEBUG)
    
    test_uris = [
        'ipp://192.168.1.16:631/ipp/print',
        'bjnp://192.168.1.7',
        'socket://192.168.1.100:9100',
    ]
    
    for uri in test_uris:
        print(f"\n测试：{uri}")
        result = check_printer_online(uri, timeout=3)
        print(f"结果：{result}")
