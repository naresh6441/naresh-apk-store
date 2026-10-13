{
  "version": 2,
  "builds": [
    {
      "source": "app.py",
      "use": "@vercel/python"
    }
  ],
  "routes": [
    {
      "src": "/(.*)",
      "destination": "app.py"
    }
  ]
}
