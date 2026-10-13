#!/bin/sh
# Build the SIP registrar image.
#   ./build.sh                    -> agentconnect-sip-registrar:<version> and :latest
#   ./build.sh 1.0.1              -> a specific version
#   REGISTRY=registry.example.com/agentconnect ./build.sh 1.0.1 --push   -> also push to your registry
#   ./build.sh 1.0.1 --save       -> also write agentconnect-sip-registrar-1.0.1.tar.gz (copy to a server, docker load)
#   PLATFORM=linux/amd64,linux/arm64 REGISTRY=… ./build.sh 1.0.1 --push   -> multi-arch (needs buildx)
set -e
cd "$(dirname "$0")"
VERSION="${1:-$(cat VERSION)}"
NAME="${REGISTRY:+$REGISTRY/}agentconnect-sip-registrar"
if [ $# -gt 0 ]; then shift; fi

if [ -n "$PLATFORM" ]; then
  docker buildx build --platform "$PLATFORM" --build-arg VERSION="$VERSION" \
    -t "$NAME:$VERSION" -t "$NAME:latest" $( [ "$1" = "--push" ] && echo --push ) .
  exit 0
fi

docker build --build-arg VERSION="$VERSION" -t "$NAME:$VERSION" -t "$NAME:latest" .
echo "built $NAME:$VERSION"
for opt in "$@"; do
  case "$opt" in
    --push) docker push "$NAME:$VERSION" && docker push "$NAME:latest" ;;
    --save) docker save "$NAME:$VERSION" | gzip > "agentconnect-sip-registrar-$VERSION.tar.gz"
            echo "saved agentconnect-sip-registrar-$VERSION.tar.gz  (on the server: docker load -i <file>)" ;;
  esac
done
