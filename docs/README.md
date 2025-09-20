# Website

This website is built using [Docusaurus](https://docusaurus.io/), a modern static site generator.

### Installation

```
$ yarn
```

### Local Development

```
$ yarn start
```

This command starts a local development server and opens a browser window. Most changes are reflected live without restarting the server.

### Build

```
$ yarn build
```

This command generates static content in the `build` directory, which can be served by any static content hosting service.

### Deployment

Using SSH:

```
$ USE_SSH=true yarn deploy
```

Not using SSH:

```
$ GIT_USER=<Your GitHub username> yarn deploy
```

### Environment Variables

The deployment scripts support a few optional environment variables:

- `USE_SSH` &ndash; deploy via SSH instead of HTTPS.
- `GIT_USER` &ndash; GitHub username for pushing to `gh-pages` when SSH is not used

Set these in your shell before running `yarn deploy`.

If you are using GitHub Pages for hosting, this command provides a convenient way to build the website and push to the `gh-pages` branch.
