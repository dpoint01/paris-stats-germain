export default {
  async fetch(request) {
    const url = new URL(request.url);
    const endpoint = url.searchParams.get('endpoint');

    // CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, {
        headers: {
          'Access-Control-Allow-Origin': '*',
          'Access-Control-Allow-Methods': 'GET, OPTIONS',
          'Access-Control-Allow-Headers': 'Content-Type',
          'Access-Control-Max-Age': '86400',
        },
      });
    }

    if (!endpoint || !endpoint.startsWith('/')) {
      return Response.json({ error: 'Missing endpoint' }, { status: 400 });
    }

    const sofaUrl = `https://api.sofascore.com/api/v1${endpoint}`;

    try {
      const response = await fetch(sofaUrl, {
        headers: {
          'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
          'Accept': 'application/json',
          'Accept-Language': 'fr-FR,fr;q=0.9',
        },
      });

      const body = await response.text();

      // Determine cache duration
      const isLineup = endpoint.includes('/lineups');
      const isPlayers = endpoint.includes('/players');
      const maxAge = isLineup ? 86400 : isPlayers ? 3600 : 300;

      return new Response(body, {
        status: response.status,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*',
          'Cache-Control': `public, s-maxage=${maxAge}, stale-while-revalidate=60`,
        },
      });
    } catch (e) {
      return Response.json({ error: e.message }, { status: 502 });
    }
  },
};
