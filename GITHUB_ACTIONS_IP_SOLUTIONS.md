# GitHub Actions IP Address Solutions

This document outlines several solutions to run GitHub Actions using the same IP address as your local machine or bypass website blocking.

## Problem

Websites like Seek.com.au, LinkedIn, and Workforce Australia detect and block requests from GitHub Actions IP ranges, preventing your automation from running in the cloud.

## Solutions

### 1. Self-Hosted GitHub Actions Runner (Recommended) ⭐

**Pros:**

- Uses your exact IP address
- Full control over environment
- No additional costs
- Most reliable solution

**Cons:**

- Requires your machine to be running
- Uses your local resources

**Setup:**

1. Run the setup script:

   ```bash
   ./scripts/setup_self_hosted_runner.sh
   ```

2. Go to your GitHub repository settings:
   `https://github.com/YOUR_USERNAME/YOUR_REPO/settings/actions/runners`

3. Click "New self-hosted runner" and follow the instructions

4. Use the workflow file: `.github/workflows/job_scraper_self_hosted.yml`

### 2. Proxy/VPN Solution

**Pros:**

- Runs on GitHub's infrastructure
- Can use residential IP addresses
- Automated scaling

**Cons:**

- Requires paid proxy service
- May be slower
- Additional complexity

**Setup:**

1. Get a proxy service (recommended: Bright Data, ProxyMesh, or Smartproxy)
2. Add proxy URL to GitHub Secrets as `PROXY_URL`
3. Use workflow file: `.github/workflows/job_scraper_proxy.yml`
4. Your scrapers now support proxy configuration via environment variables

**Proxy Configuration:**
Add to your `configs/config.yaml`:

```yaml
proxy:
  enabled: true
  http_url: 'http://username:password@proxy.example.com:8080'
  https_url: 'http://username:password@proxy.example.com:8080'
```

### 3. Tunneling Solution (Advanced)

**Pros:**

- Routes traffic through your local machine
- Uses your IP address
- Runs on GitHub infrastructure

**Cons:**

- Complex setup
- Requires tunnel service (ngrok/Cloudflare)
- May have bandwidth limits

**Setup:**

1. Set up Cloudflare Tunnel or ngrok on your local machine
2. Add tunnel tokens to GitHub Secrets
3. Use workflow file: `.github/workflows/job_scraper_tunnel.yml`

### 4. Residential Proxy Services

**Recommended Services:**

- **Bright Data**: Premium residential proxies
- **Smartproxy**: Good balance of price/performance
- **ProxyMesh**: Simple HTTP proxy service
- **Storm Proxies**: Budget-friendly option

**Configuration Example:**

```bash
# Add to GitHub Secrets
PROXY_URL=http://username:password@proxy.smartproxy.com:10000
```

## Implementation Details

### Updated Scraper Code

Your scrapers now automatically detect and use proxy configuration from:

1. Environment variables (`HTTP_PROXY`, `HTTPS_PROXY`)
2. Config file (`proxy` section)

### Testing Your Setup

1. Test locally first:

   ```bash
   export HTTP_PROXY="http://your-proxy:port"
   python -m scripts.run_job_search
   ```

2. Check your IP address:
   ```python
   import requests
   response = requests.get('https://httpbin.org/ip')
   print(response.json())
   ```

## Recommendations

1. **Start with Self-Hosted Runner** - It's the simplest and most reliable
2. **For production**: Consider a hybrid approach:
   - Self-hosted for critical scraping
   - Proxy solution as backup
3. **Monitor success rates** and switch solutions if blocking increases

## Security Considerations

- Never commit proxy credentials to your repository
- Use GitHub Secrets for all sensitive configuration
- Rotate proxy credentials regularly
- Monitor proxy usage and costs

## Troubleshooting

### Common Issues:

1. **"Connection refused"**: Check proxy URL format
2. **"Authentication failed"**: Verify proxy credentials
3. **Slow performance**: Try different proxy endpoints
4. **Still getting blocked**: The proxy IP might also be blocked

### Debug Commands:

```bash
# Test proxy connection
curl -x http://proxy:port https://httpbin.org/ip

# Check if your IP is blocked
curl https://www.seek.com.au/

# Test with different User-Agent
curl -H "User-Agent: Mozilla/5.0..." https://www.seek.com.au/
```

## Cost Estimates

- **Self-hosted**: Free (uses your electricity/internet)
- **Residential Proxies**: $50-200/month depending on usage
- **Tunnel Services**: $5-20/month for basic plans
- **VPS with VPN**: $5-15/month

Choose the solution that best fits your budget and reliability requirements.
