# Vite dev server. This is deliberately not a production image: the dashboard is an
# operational/documentation surface for the demo, and `vite build` + a static server
# would hide the hot-reload loop it is used in. See ARCHITECTURE.md.
FROM node:22-alpine

WORKDIR /app

# Dependencies first, so a source edit does not reinstall the tree.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 5173
CMD ["npm", "run", "dev"]
