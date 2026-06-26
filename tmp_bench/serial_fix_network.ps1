$port = New-Object System.IO.Ports.SerialPort COM3,1500000,None,8,one
$port.Open()
Start-Sleep -Milliseconds 300
while ($port.BytesToRead -gt 0) { $port.ReadExisting() | Out-Null }

# 1. 恢复 NM 配置 - 用简单命令
$port.WriteLine("echo toybrick | sudo -S sed -i 's/managed=true/managed=false/' /etc/NetworkManager/NetworkManager.conf")
Start-Sleep -Milliseconds 3000
$r1 = ""
while ($port.BytesToRead -gt 0) { $r1 += $port.ReadExisting(); Start-Sleep -Milliseconds 300 }

# 2. 给 eth0 配静态 IP
$port.WriteLine("echo toybrick | sudo -S ip addr add 192.168.1.200/24 dev eth0")
Start-Sleep -Milliseconds 2000
$r2 = ""
while ($port.BytesToRead -gt 0) { $r2 += $port.ReadExisting(); Start-Sleep -Milliseconds 200 }

# 3. 激活 eth0
$port.WriteLine("echo toybrick | sudo -S ip link set eth0 up")
Start-Sleep -Milliseconds 2000
$r3 = ""
while ($port.BytesToRead -gt 0) { $r3 += $port.ReadExisting(); Start-Sleep -Milliseconds 200 }

# 4. 重启 NM
$port.WriteLine("echo toybrick | sudo -S systemctl restart NetworkManager")
Start-Sleep -Milliseconds 5000
$r4 = ""
while ($port.BytesToRead -gt 0) { $r4 += $port.ReadExisting(); Start-Sleep -Milliseconds 300 }

# 5. 查看网络状态
$port.WriteLine("nmcli device status")
Start-Sleep -Milliseconds 2000
$r5 = ""
while ($port.BytesToRead -gt 0) { $r5 += $port.ReadExisting(); Start-Sleep -Milliseconds 200 }

# 6. 查看启动时间
$port.WriteLine("systemd-analyze")
Start-Sleep -Milliseconds 2000
$r6 = ""
while ($port.BytesToRead -gt 0) { $r6 += $port.ReadExisting(); Start-Sleep -Milliseconds 200 }

$port.Close()

Write-Output "=== Step 1: NM配置恢复 ==="
Write-Output $r1
Write-Output "=== Step 2: eth0配IP ==="
Write-Output $r2
Write-Output "=== Step 3: eth0激活 ==="
Write-Output $r3
Write-Output "=== Step 4: NM重启 ==="
Write-Output $r4
Write-Output "=== Step 5: 网络状态 ==="
Write-Output $r5
Write-Output "=== Step 6: 启动时间 ==="
Write-Output $r6
