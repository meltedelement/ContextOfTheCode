# Context of the Code — Frontend

React dashboard for the metrics API. Built with Vite, TypeScript, and React 18.

## Prerequisites

- Node.js 18+
- Backend Flask API running on `http://localhost:5000` (see project root)

## Setup

```bash
cd frontend
npm install
```

## Development

```bash
npm run dev
```

Runs the app at [http://localhost:5173](http://localhost:5173). API requests to `/api` and `/health` are proxied to the Flask server on port 5000, so you can run both without CORS.

1. Start the Flask server from the project root (e.g. `python server/app.py` or via `run_all.py`).
2. Start the frontend: `npm run dev`.

## Build

```bash
npm run build
```

Output is in `dist/`. For production, serve `dist/` and point the app at your API (e.g. via env or a reverse proxy).

## Scripts

| Script   | Description        |
|----------|--------------------|
| `npm run dev`     | Start dev server with proxy |
| `npm run build`   | TypeScript check + production build |
| `npm run lint`    | Run ESLint |
| `npm run preview` | Preview production build locally |
