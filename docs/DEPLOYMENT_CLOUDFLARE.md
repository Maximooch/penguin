# Deploying Penguin with Cloudflare

This guide covers deploying Penguin to handle GitHub webhooks using Cloudflare, with two approaches: Cloudflare Tunnel (easiest) and traditional Nginx setup.

---

## 🚀 Option 1: Cloudflare Tunnel (RECOMMENDED)

**Best for:** Quick setup, home servers, no port forwarding needed

### Prerequisites
- Cloudflare account with domain configured (penguinagents.com)
- Docker installed
- Penguin container built

### Step 1: Install cloudflared

**Linux/macOS:**
```bash
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o cloudflared
chmod +x cloudflared
sudo mv cloudflared /usr/local/bin/
```

**macOS (Homebrew):**
```bash
brew install cloudflare/cloudflare/cloudflared
```

**Windows:**
Download from: https://github.com/cloudflare/cloudflared/releases

### Step 2: Authenticate

```bash
cloudflared tunnel login
```
- Browser opens automatically
- Log in to Cloudflare
- Select `penguinagents.com` domain
- Authorization file saved to `~/.cloudflared/cert.pem`

### Step 3: Create Tunnel

```bash
cloudflared tunnel create penguin
```

**Output:**
```
Created tunnel penguin with id abc123-def456-ghi789
Credentials written to: /home/user/.cloudflared/abc123-def456-ghi789.json
```

**Save your Tunnel ID!** You'll need it in the next step.

### Step 4: Configure Tunnel

Create configuration file:
```bash
mkdir -p ~/.cloudflared
nano ~/.cloudflared/config.yml
```

**Configuration:**
```yaml
tunnel: abc123-def456-ghi789  # Replace with YOUR tunnel ID
credentials-file: /home/YOUR_USERNAME/.cloudflared/abc123-def456-ghi789.json

ingress:
  # Route all traffic to local Penguin container
  - hostname: penguinagents.com
    service: http://localhost:8000

  # Optional: route subdomain for webhooks specifically
  # - hostname: api.penguinagents.com
  #   service: http://localhost:8000

  # Catch-all (required)
  - service: http_status:404
```

### Step 5: Route DNS

Create DNS record pointing to your tunnel:
```bash
cloudflared tunnel route dns penguin penguinagents.com
```

**Output:**
```
Created CNAME record for penguinagents.com -> abc123-def456-ghi789.cfargotunnel.com
```

Verify in Cloudflare dashboard (DNS tab) - you should see a new CNAME record.

### Step 6: Start Penguin Container

```bash
docker run -d \
  --name penguin-web \
  -p 8000:8000 \
  --restart unless-stopped \
  -e GITHUB_WEBHOOK_SECRET=your-webhook-secret-here \
  -e GITHUB_APP_ID=1622624 \
  -e GITHUB_APP_INSTALLATION_ID=88065184 \
  -e GITHUB_APP_PRIVATE_KEY_PATH=/secrets/github-app.pem \
  -e GITHUB_REPOSITORY=Maximooch/penguin \
  -v ~/.penguin/secrets/github-app.pem:/secrets/github-app.pem:ro \
  penguin:web-local
```

### Step 7: Start Cloudflare Tunnel

**Option A: Run in foreground (testing):**
```bash
cloudflared tunnel run penguin
```

**Option B: Run as systemd service (production):**
```bash
# Install service
sudo cloudflared service install

# Start and enable
sudo systemctl start cloudflared
sudo systemctl enable cloudflared

# Check status
sudo systemctl status cloudflared

# View logs
sudo journalctl -u cloudflared -f
```

### Step 8: Verify Deployment

```bash
# Test health endpoint
curl https://penguinagents.com/api/v1/health

# Expected response:
# {"status":"healthy","core_initialized":true,...}
```

### Step 9: Configure GitHub Webhook

1. Go to: `https://github.com/settings/apps/penguin-agent`
2. Scroll to **Webhook** section
3. Set **Webhook URL:** `https://penguinagents.com/api/v1/integrations/github/webhook`
4. Set **Webhook secret:** (your generated secret)
5. Ensure **Active** is checked
6. Click **Save changes**

### Step 10: Test Webhook

Trigger a test event (comment on a PR, create an issue) and check:

**GitHub webhook deliveries:**
```
Settings → Apps → Penguin Agent → Advanced → Recent Deliveries
```

**Cloudflared logs:**
```bash
sudo journalctl -u cloudflared -f
```

**Penguin logs:**
```bash
docker logs -f penguin-web
```

---

## 🔧 Option 2: Traditional Setup (Cloudflare + Nginx)

**Best for:** VPS with public IP, production deployments, more control

### Prerequisites
- Server with public static IP
- Domain configured in Cloudflare
- Docker installed

### Step 1: Configure Cloudflare DNS

1. Log in to Cloudflare dashboard
2. Select `penguinagents.com`
3. Go to **DNS** tab
4. Add **A record**:
   - **Name:** `@` (root domain) or `api` (subdomain)
   - **IPv4 address:** Your server's public IP (e.g., `123.45.67.89`)
   - **Proxy status:** ☁️ Proxied (orange cloud)
   - **TTL:** Auto
5. Click **Save**

### Step 2: Configure Cloudflare SSL

1. Go to **SSL/TLS** tab
2. Choose encryption mode:
   - **Flexible:** Cloudflare ↔ Origin uses HTTP (easier, less secure)
   - **Full:** Cloudflare ↔ Origin uses self-signed SSL
   - **Full (strict):** Cloudflare ↔ Origin uses valid SSL cert (most secure)

**For this guide, we'll use Flexible mode** (simpler setup).

### Step 3: Install Nginx

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install nginx -y
```

**CentOS/RHEL:**
```bash
sudo yum install nginx -y
```

**Start Nginx:**
```bash
sudo systemctl start nginx
sudo systemctl enable nginx
```

### Step 4: Configure Nginx

Create site configuration:
```bash
sudo nano /etc/nginx/sites-available/penguinagents.com
```

**Configuration:**
```nginx
server {
    server_name penguinagents.com www.penguinagents.com;
    listen 80;

    # Max body size for file uploads
    client_max_body_size 50M;

    # API routes - proxy to Penguin container
    location /api/ {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;

        # WebSocket support
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        # Preserve original request info
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Important: preserve raw body for webhook signature verification
        proxy_request_buffering off;

        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    # Root path
    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Access logs
    access_log /var/log/nginx/penguinagents_access.log;
    error_log /var/log/nginx/penguinagents_error.log;
}
```

### Step 5: Enable Site

```bash
# Create symbolic link
sudo ln -s /etc/nginx/sites-available/penguinagents.com /etc/nginx/sites-enabled/

# Remove default site (optional)
sudo rm /etc/nginx/sites-enabled/default

# Test configuration
sudo nginx -t

# Reload nginx
sudo systemctl reload nginx
```

### Step 6: Configure Firewall

**UFW (Ubuntu):**
```bash
sudo ufw allow 'Nginx Full'
sudo ufw allow OpenSSH
sudo ufw enable
sudo ufw status
```

**Firewalld (CentOS):**
```bash
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload
```

### Step 7: Start Penguin Container

```bash
docker run -d \
  --name penguin-web \
  -p 8000:8000 \
  --restart unless-stopped \
  -e GITHUB_WEBHOOK_SECRET=your-webhook-secret-here \
  -e GITHUB_APP_ID=1622624 \
  -e GITHUB_APP_INSTALLATION_ID=88065184 \
  -e GITHUB_APP_PRIVATE_KEY_PATH=/secrets/github-app.pem \
  -e GITHUB_REPOSITORY=Maximooch/penguin \
  -v ~/.penguin/secrets/github-app.pem:/secrets/github-app.pem:ro \
  penguin:web-local
```

### Step 8: Verify Deployment

**Test locally:**
```bash
curl http://localhost:8000/api/v1/health
```

**Test via domain:**
```bash
curl https://penguinagents.com/api/v1/health
```

**Check nginx logs:**
```bash
sudo tail -f /var/log/nginx/penguinagents_access.log
```

### Step 9: Configure GitHub Webhook

Same as Option 1, Step 9.

---

## 🔍 Troubleshooting

### Cloudflare Tunnel Issues

**Tunnel won't start:**
```bash
# Check tunnel status
cloudflared tunnel info penguin

# Test tunnel locally
cloudflared tunnel run penguin --loglevel debug
```

**DNS not resolving:**
```bash
# Check DNS propagation
dig penguinagents.com
nslookup penguinagents.com

# Verify CNAME exists in Cloudflare dashboard
```

**Connection refused:**
```bash
# Check if Penguin is running
docker ps | grep penguin

# Check if port 8000 is listening
netstat -tlnp | grep 8000

# Test local connection
curl http://localhost:8000/api/v1/health
```

### Nginx Issues

**502 Bad Gateway:**
```bash
# Check if Penguin container is running
docker ps

# Check nginx error logs
sudo tail -f /var/log/nginx/penguinagents_error.log

# Test upstream
curl http://localhost:8000/api/v1/health
```

**403 Forbidden:**
```bash
# Check nginx permissions
ls -la /var/log/nginx/

# Check SELinux (CentOS/RHEL)
sudo setenforce 0  # Temporarily disable for testing
```

**Configuration errors:**
```bash
# Test nginx config
sudo nginx -t

# Check syntax errors in config file
```

### Webhook Issues

**GitHub can't reach webhook:**
- Verify URL is publicly accessible
- Check Cloudflare SSL mode (use Flexible or Full)
- Test webhook URL in browser

**Signature verification fails:**
- Ensure `GITHUB_WEBHOOK_SECRET` matches GitHub App setting
- Check webhook endpoint preserves raw body (`proxy_request_buffering off`)

**No events received:**
- Check GitHub webhook deliveries (Recent Deliveries tab)
- Verify events are subscribed (issue_comment, pull_request, etc.)
- Check Penguin logs: `docker logs -f penguin-web`

---

## 🔒 Security Best Practices

### Cloudflare Settings

1. **SSL/TLS:**
   - Use "Full (strict)" mode for production
   - Enable "Always Use HTTPS"

2. **Firewall:**
   - Enable Bot Fight Mode
   - Add rate limiting rules for `/api/v1/integrations/github/webhook`

3. **DDoS Protection:**
   - Enable "Under Attack Mode" if needed
   - Configure Page Rules for API endpoints

### Server Hardening

**Restrict Docker port access:**
```bash
# Only listen on localhost
docker run -p 127.0.0.1:8000:8000 penguin:web-local
```

**Keep secrets secure:**
```bash
# Proper permissions on PEM file
chmod 600 ~/.penguin/secrets/github-app.pem

# Don't log secrets
# Check: docker logs penguin-web | grep -i secret
```

**Regular updates:**
```bash
# Update system packages
sudo apt update && sudo apt upgrade -y

# Update Docker images
docker pull penguin:web-local
```

---

## 📊 Monitoring

### Cloudflare Analytics

View in dashboard:
- **Analytics** tab: Traffic overview
- **Security** → **Events**: Firewall events
- **Traffic** → **Origin Reachability**: Uptime monitoring

### Application Logs

**Penguin logs:**
```bash
docker logs -f penguin-web
```

**Nginx logs:**
```bash
sudo tail -f /var/log/nginx/penguinagents_access.log
sudo tail -f /var/log/nginx/penguinagents_error.log
```

**Cloudflared logs:**
```bash
sudo journalctl -u cloudflared -f
```

### Health Monitoring

Set up external monitoring:
- [UptimeRobot](https://uptimerobot.com/) - Free uptime monitoring
- [Healthchecks.io](https://healthchecks.io/) - Cron job monitoring
- Cloudflare Health Checks (paid feature)

**Monitor endpoint:**
```
https://penguinagents.com/api/v1/health
```

---

## 🚀 Next Steps

1. **Implement webhook endpoint** (see PHASE_2.5_GITHUB_APP_CONFIG.md)
2. **Test @Penguin mentions** in GitHub issues/PRs
3. **Set up monitoring** for uptime and errors
4. **Configure backups** for conversation data
5. **Scale horizontally** if needed (load balancing)

---

## 📚 References

- [Cloudflare Tunnel Docs](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/)
- [Nginx Proxy Configuration](https://nginx.org/en/docs/http/ngx_http_proxy_module.html)
- [Cloudflare SSL Modes](https://developers.cloudflare.com/ssl/origin-configuration/ssl-modes/)
- [GitHub Webhook Docs](https://docs.github.com/en/webhooks)
- [Phase 2.5 Configuration Guide](./PHASE_2.5_GITHUB_APP_CONFIG.md)
