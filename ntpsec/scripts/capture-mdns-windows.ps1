# Native Windows counterpart to the pinned Python ephemeral-socket capture.
function Invoke-MdnsCapture([string]$SpecBase64) {
    $ErrorActionPreference = 'Stop'
    $spec = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($SpecBase64)) | ConvertFrom-Json
    $queries = [Collections.Generic.List[object]]::new()
    $replies = [Collections.Generic.List[object]]::new()
    $result = [ordered]@{ queries = $queries; replies = $replies; completed = $false }
    $udp = $null
    try {
        $address = [Net.IPAddress]::Parse($spec.source_ipv4)
        $udp = [Net.Sockets.UdpClient]::new([Net.IPEndPoint]::new($address, 0))
        $udp.Client.ReceiveTimeout = 1000
        $udp.Client.SetSocketOption([Net.Sockets.SocketOptionLevel]::IP, [Net.Sockets.SocketOptionName]::MulticastTimeToLive, 255)
        $udp.Client.SetSocketOption([Net.Sockets.SocketOptionLevel]::IP, [Net.Sockets.SocketOptionName]::MulticastInterface, $address.GetAddressBytes())
        foreach ($query in $spec.queries) {
            $packet = [Convert]::FromBase64String($query.query_base64)
            $item = [ordered]@{ name = $query.name; type = $query.type; query_base64 = $query.query_base64; epoch_ms = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() }
            $queries.Add($item)
            $item.bytes_sent = $udp.Send($packet, $packet.Length, '224.0.0.251', 5353)
            $item.socket_address = @($udp.Client.LocalEndPoint.Address.ToString(), $udp.Client.LocalEndPoint.Port)
            $watch = [Diagnostics.Stopwatch]::StartNew()
            while ($watch.Elapsed.TotalSeconds -lt 3 -and $replies.Count -lt 64) {
                $source = [Net.IPEndPoint]::new([Net.IPAddress]::Any, 0)
                try { $raw = $udp.Receive([ref]$source) }
                catch {
                    $inner = $_.Exception
                    while ($inner.InnerException) { $inner = $inner.InnerException }
                    if ($inner -is [Net.Sockets.SocketException] -and $inner.SocketErrorCode -eq [Net.Sockets.SocketError]::TimedOut) { continue }
                    throw
                }
                $size = [Math]::Min($raw.Length, 9001)
                $replies.Add([ordered]@{
                    query_index = $queries.Count - 1
                    source = @($source.Address.ToString(), $source.Port)
                    epoch_ms = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
                    bytes = $size
                    possibly_truncated = $raw.Length -ge 9001
                    base64 = [Convert]::ToBase64String($raw, 0, $size)
                })
            }
        }
        $result.completed = $true
    }
    catch { $result.error = $_.Exception.Message }
    finally {
        if ($null -ne $udp) { $udp.Dispose() }
        $result.reply_limit_reached = $replies.Count -eq 64
        $result | ConvertTo-Json -Depth 8 -Compress
    }
}
