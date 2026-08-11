package io.github.mikehstudio.rostelemetry;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;

final class JsonSupport {
    static final ObjectMapper MAPPER = new ObjectMapper();

    private JsonSupport() {}

    static String write(JsonNode node) {
        try {
            return MAPPER.writeValueAsString(node);
        } catch (JsonProcessingException exception) {
            throw new IllegalArgumentException("Cannot serialize telemetry JSON", exception);
        }
    }

    static ObjectNode object() {
        return MAPPER.createObjectNode();
    }

    static String sha256(Object... parts) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            for (int index = 0; index < parts.length; index++) {
                if (index > 0) {
                    digest.update((byte) 0x1f);
                }
                digest.update(String.valueOf(parts[index]).getBytes(StandardCharsets.UTF_8));
            }
            return HexFormat.of().formatHex(digest.digest());
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 is unavailable", exception);
        }
    }
}
