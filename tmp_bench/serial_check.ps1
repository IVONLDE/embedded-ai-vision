$port = New-Object System.IO.Ports.SerialPort COM3,1500000,None,8,one
$port.Open()
Start-Sleep -Milliseconds 300
while ($port.BytesToRead -gt 0) { $port.ReadExisting() | Out-Null }

# 查看 IP 地址
$port.WriteLine("ip addr show eth0")
Start-Sleep -Milliseconds 2000
$r1 = ""
while ($port.BytesToRead -gt 0) { $r1 += $port.ReadExisting(); Start-Sleep -Milliseconds 200 }

# 查看 SSH 服务
$port.WriteLine("systemctl status ssh --no-pager")
Start-Sleep -Milliseconds 2000
$r2 = ""
while ($port.BytesToRead -gt 0) { $r2 += $port.ReadExisting(); Start-Sleep -Milliseconds 200 }

# 尝试 ping Windows
$port.WriteLine("ping -c 2 192.168.1.100")
Start-Sleep -Milliseconds 4000
$r3 = ""
while ($port.BytesToRead -gt 0) { $r3 += $port.ReadExisting(); Start-Sleep -Milliseconds 200 }

$port.Close()

Write-Output "=== eth0 IP ==="
Write-Output $r1
Write-Output "=== SSH 状态 ==="
Write-Output $r2
Write-Output "=== Ping Windows ==="
Write-Output $r3
