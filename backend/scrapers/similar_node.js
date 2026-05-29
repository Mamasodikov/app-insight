const gplay = require('google-play-scraper').default;
const [appId, country, num] = process.argv.slice(2);
gplay.similar({
  appId: appId || 'com.example',
  country: country || 'us',
  num: parseInt(num) || 15,
  fullDetail: false,
}).then(results => {
  const out = results.map(a => ({
    app_id: a.appId,
    title: a.title,
    developer: a.developer,
    rating: a.scoreText ? parseFloat(a.scoreText) : a.score,
    icon_url: a.icon,
    installs: a.installs,
    price: a.price || 0,
    store: 'playstore',
  }));
  process.stdout.write(JSON.stringify(out));
}).catch(() => {
  process.stdout.write('[]');
});
