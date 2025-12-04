# 🎮 Twitch Streaming Opportunity Analyzer - Web App

## 🚀 QUICK START

### Backend (Flask API)

1. **Install dependencies:**
```bash
pip install flask flask-cors python-dotenv twitchAPI
```

2. **Set up environment:**
Create `twitch.key.ring.env`:
```
TWITCH_APP_ID=your_app_id_here
TWITCH_APP_SECRET=your_secret_here
```

3. **Run backend:**
```bash
python webapp_backend.py
```

Backend runs on: `http://localhost:5000`

### Frontend (Next.js)

1. **Install Node.js dependencies:**
```bash
cd webapp-frontend
npm install
```

2. **Run development server:**
```bash
npm run dev
```

Frontend runs on: `http://localhost:3000`

---

## 📦 PRODUCTION DEPLOYMENT

### Option 1: Vercel (Frontend) + Railway (Backend) - RECOMMENDED

#### Deploy Backend to Railway:

1. Sign up at https://railway.app
2. Click "New Project" → "Deploy from GitHub repo"
3. Connect your repo with `webapp_backend.py`
4. Add environment variables:
   - `TWITCH_APP_ID`
   - `TWITCH_APP_SECRET`
5. Railway auto-deploys and gives you a URL like: `https://your-app.up.railway.app`

#### Deploy Frontend to Vercel:

1. Sign up at https://vercel.com
2. Click "New Project" → Import from GitHub
3. Select the `webapp-frontend` folder
4. Add environment variable:
   - `NEXT_PUBLIC_API_URL` = your Railway backend URL
5. Deploy! Vercel gives you: `https://your-app.vercel.app`

**Total Cost:** $0 (free tiers) - $5/month (if you exceed free tier)

---

### Option 2: Single VPS (DigitalOcean, AWS, etc.)

#### Setup Ubuntu 22.04 Server:

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python
sudo apt install python3 python3-pip -y

# Install Node.js
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install nodejs -y

# Install nginx
sudo apt install nginx -y

# Install PM2 for process management
sudo npm install -g pm2
```

#### Deploy Backend:

```bash
# Clone your repo
git clone your-repo-url
cd your-repo

# Install Python dependencies
pip3 install flask flask-cors python-dotenv twitchAPI

# Create environment file
nano twitch.key.ring.env
# Add your credentials

# Start with PM2
pm2 start webapp_backend.py --name twitch-backend --interpreter python3
pm2 save
pm2 startup
```

#### Deploy Frontend:

```bash
cd webapp-frontend

# Set environment variable
export NEXT_PUBLIC_API_URL=http://your-server-ip:5000

# Build production
npm install
npm run build

# Start with PM2
pm2 start npm --name twitch-frontend -- start
pm2 save
```

#### Configure Nginx:

```bash
sudo nano /etc/nginx/sites-available/twitch-analyzer
```

Add:
```nginx
server {
    listen 80;
    server_name your-domain.com;

    # Frontend
    location / {
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }

    # Backend API
    location /api {
        proxy_pass http://localhost:5000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

```bash
# Enable site
sudo ln -s /etc/nginx/sites-available/twitch-analyzer /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

#### Add SSL (Let's Encrypt):

```bash
sudo apt install certbot python3-certbot-nginx -y
sudo certbot --nginx -d your-domain.com
```

**Monthly Cost:** $5-10 (DigitalOcean Droplet)

---

## 💰 MONETIZATION SETUP

### 1. Google AdSense

1. Apply at: https://www.google.com/adsense
2. Get approved (requires decent traffic)
3. Add ad code to `app/page.tsx`

Example placement:
```tsx
{/* Ad between game cards */}
{game.rank % 10 === 0 && (
  <div className="my-4">
    {/* Your AdSense code here */}
  </div>
)}
```

### 2. Steam Affiliate Program

**Currently:** Steam doesn't have a direct affiliate program

**Alternatives:**
- **Kinguin Affiliate:** https://www.kinguin.net/affiliate
- **G2A Affiliate:** https://www.g2a.com/affiliate-program
- **Green Man Gaming:** https://www.greenmangaming.com/vip/

**Update `get_purchase_links()` in backend:**
```python
def get_purchase_links(game_name):
    # Add your affiliate IDs
    KINGUIN_AFFILIATE_ID = "your_id"
    
    links = {
        "steam": f"https://www.kinguin.net/search?text={game_name}&aff={KINGUIN_AFFILIATE_ID}",
        "epic": f"https://store.epicgames.com/search?q={game_name}",
        "free": False
    }
    return links
```

### 3. Epic Games Creator Code

1. Apply: https://www.epicgames.com/affiliate/
2. Get approved
3. Add your creator code to Epic links:

```python
EPIC_CREATOR_CODE = "YOUR_CODE"
epic_link = f"https://store.epicgames.com/en-US/browse?q={game_name}&creator={EPIC_CREATOR_CODE}"
```

---

## 📊 ANALYTICS SETUP

### Google Analytics

1. Create account: https://analytics.google.com
2. Get tracking ID
3. Add to `app/layout.tsx`:

```tsx
import Script from 'next/script'

export default function RootLayout({ children }) {
  return (
    <html>
      <head>
        <Script
          src={`https://www.googletagmanager.com/gtag/js?id=GA_MEASUREMENT_ID`}
          strategy="afterInteractive"
        />
        <Script id="google-analytics" strategy="afterInteractive">
          {`
            window.dataLayer = window.dataLayer || [];
            function gtag(){dataLayer.push(arguments);}
            gtag('js', new Date());
            gtag('config', 'GA_MEASUREMENT_ID');
          `}
        </Script>
      </head>
      <body>{children}</body>
    </html>
  )
}
```

---

## 🎯 SEO OPTIMIZATION

### Update metadata in `app/layout.tsx`:

```typescript
export const metadata: Metadata = {
  title: 'Best Games to Stream on Twitch 2025 | Streaming Opportunity Analyzer',
  description: 'Find the best games to stream on Twitch with real-time competition analysis. Discover streaming opportunities with less competition and better growth potential.',
  keywords: 'best games to stream, twitch streaming, streaming opportunities, grow twitch channel, streamer tools, twitch analytics',
  openGraph: {
    title: 'Twitch Streaming Opportunity Analyzer',
    description: 'Real-time analysis of the best games to stream',
    images: ['/og-image.png'],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Twitch Streaming Opportunity Analyzer',
    description: 'Find the best games to stream right now',
  },
}
```

### Create sitemap.xml:

```bash
cd webapp-frontend/public
nano sitemap.xml
```

```xml
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://your-domain.com/</loc>
    <lastmod>2025-01-01</lastmod>
    <changefreq>hourly</changefreq>
    <priority>1.0</priority>
  </url>
</urlset>
```

Submit to:
- Google Search Console
- Bing Webmaster Tools

---

## 🔧 MAINTENANCE

### Monitor Backend Health:

```bash
curl https://your-backend-url.com/api/v1/health
```

### Clear Cache Manually:

```bash
curl -X POST https://your-backend-url.com/api/v1/clear-cache
```

### View PM2 Logs:

```bash
pm2 logs twitch-backend
pm2 logs twitch-frontend
```

### Restart Services:

```bash
pm2 restart twitch-backend
pm2 restart twitch-frontend
```

---

## 🚨 TROUBLESHOOTING

### Backend won't start:
- Check Twitch credentials in `.env`
- Verify Python 3.10+ installed
- Check port 5000 isn't in use: `lsof -i :5000`

### Frontend won't connect to backend:
- Verify `NEXT_PUBLIC_API_URL` environment variable
- Check CORS is enabled in backend
- Test backend directly: `curl http://backend-url/api/v1/analyze`

### Rate limit warnings:
- Normal! The twitchAPI library handles these automatically
- They're logged but don't break functionality
- If persistent, increase cache time in backend

---

## 📈 GROWTH STRATEGY

### Phase 1: Launch (Month 1)
- Deploy to production
- Submit to Google/Bing
- Post on r/Twitch, r/streaming
- **Target:** 1k visitors

### Phase 2: Content (Months 2-3)
- Write blog posts: "Top 10 Underrated Games to Stream"
- Create YouTube tutorials referencing your site
- Guest post on streaming blogs
- **Target:** 10k monthly visitors

### Phase 3: Premium (Month 4+)
- Add user accounts
- Premium tier: Advanced features for $4.99/month
- Email alerts for opportunities
- **Target:** 100+ paying users

---

## 💵 REVENUE ESTIMATES

### Conservative (1k daily visitors):
- Ad revenue: $100-200/month
- Affiliate clicks (2%): $300/month
- **Total: $400-500/month**

### Growth (10k daily visitors):
- Ad revenue: $1,000-2,000/month
- Affiliate clicks: $3,000/month
- Premium users (100 @ $4.99): $500/month
- **Total: $4,500-5,500/month**

---

## 🎨 CUSTOMIZATION

### Change colors:
Edit `tailwind.config.js`:
```javascript
colors: {
  'matrix-green': '#00ff00',  // Change to your brand color
}
```

### Update branding:
- Edit header in `app/page.tsx`
- Replace "DIGITALVOCALS" with your brand
- Add logo in `public/` folder

---

## 📝 TODO / FUTURE FEATURES

- [ ] User accounts (Auth0 or Clerk)
- [ ] Save favorite games
- [ ] Email alerts when games become opportunities
- [ ] Historical trend charts
- [ ] Peak vs off-peak time analysis
- [ ] Stream schedule optimizer
- [ ] Mobile app (React Native)
- [ ] Discord bot integration

---

## 🆘 SUPPORT

Questions? Issues?
- Check GitHub Issues
- Email: your-email@example.com
- Discord: your-discord-link

---

**Built by DIGITALVOCALS**  
**Last Updated:** December 2024  
**Version:** 2.0.0
