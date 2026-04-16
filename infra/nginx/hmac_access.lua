-- Optional request integrity enforcement for /ingest endpoints.
-- Expected:
--   X-Signature-Timestamp: unix epoch seconds
--   X-Signature: hex HMAC-SHA256 over "<timestamp>.<raw_body>"
--
-- Secret source:
--   /etc/nginx/secrets/aiops_hmac_secret
--
-- Note:
-- - Requires OpenResty or nginx lua module with lua-resty-string and lua-resty-openssl.
-- - Keep a small replay window to reduce replay attacks.

local timestamp = ngx.var.http_x_signature_timestamp
local signature = ngx.var.http_x_signature

if not timestamp or not signature then
    return ngx.exit(401)
end

local ts_num = tonumber(timestamp)
if not ts_num then
    return ngx.exit(401)
end

local now = ngx.time()
if math.abs(now - ts_num) > 300 then
    return ngx.exit(401)
end

local secret_file = "/etc/nginx/secrets/aiops_hmac_secret"
local file = io.open(secret_file, "r")
if not file then
    ngx.log(ngx.ERR, "hmac secret file not found: ", secret_file)
    return ngx.exit(500)
end
local secret = file:read("*a")
file:close()
secret = secret:gsub("%s+$", "")

ngx.req.read_body()
local body = ngx.req.get_body_data() or ""
local payload = timestamp .. "." .. body

local hmac = require("resty.openssl.hmac")
local str = require("resty.string")
local ctx, err = hmac.new(secret, "sha256")
if not ctx then
    ngx.log(ngx.ERR, "hmac init failed: ", err)
    return ngx.exit(500)
end

ctx:update(payload)
local digest = ctx:final()
local expected = str.to_hex(digest)

if expected ~= signature then
    return ngx.exit(401)
end
