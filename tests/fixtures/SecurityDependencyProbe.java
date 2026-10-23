package securityprobe;

import java.util.BitSet;
import java.util.ServiceLoader;

/** Trusted synthetic checks against the assembled runtime, never user bytecode. */
public final class SecurityDependencyProbe {
    private static int checks;
    private static void check(boolean ok, String label) {
        if (!ok) throw new AssertionError(label);
        checks++;
        System.out.println("PASS " + label);
    }

    public static final class UntrustedString {
        static int constructed;
        public UntrustedString(String ignored) { constructed++; }
    }

    public static void main(String[] args) throws Exception {
        var config = new org.apache.hadoop.conf.Configuration(false);
        config.set("local.ee.synthetic", "影像🌍");
        check("影像🌍".equals(config.get("local.ee.synthetic")), "Hadoop Configuration Unicode");
        var fs = org.apache.hadoop.fs.FileSystem.getLocal(config);
        check("file".equals(fs.getUri().getScheme()), "Hadoop local filesystem");
        check(Class.forName("org.apache.hadoop.io.serializer.avro.AvroSpecificSerialization") != null,
                "Hadoop Avro serializer retained");

        var mapper = new org.apache.hadoop.shaded.com.fasterxml.jackson.databind.ObjectMapper();
        check("影像🌍".equals(mapper.readTree("{\"v\":\"影像🌍\"}").get("v").asText()),
                "Actual Hadoop shaded JSON");
        check("2.18.12".equals(mapper.version().toString()), "Hadoop Jackson patched version");
        mapper.getFactory().setStreamReadConstraints(
                org.apache.hadoop.shaded.com.fasterxml.jackson.core.StreamReadConstraints.builder()
                        .maxNestingDepth(8).build());
        boolean denied = false;
        try { mapper.readTree("[".repeat(20) + "0" + "]".repeat(20)); }
        catch (org.apache.hadoop.shaded.com.fasterxml.jackson.core.exc.StreamConstraintsException expected) {
            denied = true;
        }
        check(denied, "Shaded JSON nesting constraint enforced");
        check(ServiceLoader.load(org.apache.hadoop.shaded.com.fasterxml.jackson.core.JsonFactory.class)
                .iterator().hasNext(), "Hadoop relocated service provider");
        var parquet = new shaded.parquet.com.fasterxml.jackson.databind.ObjectMapper();
        check(parquet.readTree("{\"rows\":3}").get("rows").asInt() == 3,
                "Actual Parquet metadata JSON");
        check("2.21.7".equals(parquet.version().toString()), "Parquet Jackson patched version");
        check(ServiceLoader.load(shaded.parquet.com.fasterxml.jackson.core.JsonFactory.class)
                .iterator().hasNext(), "Parquet relocated service provider");
        check("2.21.7".equals(new com.fasterxml.jackson.databind.ObjectMapper().version().toString()),
                "Unshaded Jackson matching Spark version line");

        var properties = new org.apache.hadoop.shaded.org.apache.commons.configuration2.PropertiesConfiguration();
        properties.setProperty("synthetic", "影像");
        check("影像".equals(properties.getString("synthetic")), "Shaded Configuration2/Lang3 linkage");
        var txns = new org.apache.hadoop.hive.common.ValidReadTxnList(new long[]{3, 5}, new BitSet(), 10, 3);
        check(!txns.isTxnValid(3), "Hive storage invalid transaction");
        txns.removeException(3);
        check(txns.isTxnValid(3), "Hive storage actual Lang3 array API");
        new org.apache.hadoop.hive.common.ValidReadTxnList("");
        check(true, "Hive storage actual Lang3 CharSequence API");

        // Ordinary data must work without widening Avro's java-class allowlist.
        var schema = new org.apache.hadoop.shaded.org.apache.avro.Schema.Parser().parse("\"string\"");
        var reader = new org.apache.hadoop.shaded.org.apache.avro.specific.SpecificDatumReader<Object>(schema);
        var decoder = org.apache.hadoop.shaded.org.apache.avro.io.DecoderFactory.get().jsonDecoder(schema, "\"12.5\"");
        check("12.5".equals(reader.read(null, decoder).toString()), "Avro ordinary string decoding");
        schema = new org.apache.hadoop.shaded.org.apache.avro.Schema.Parser().parse(
                "{\"type\":\"string\",\"java-class\":\"securityprobe.SecurityDependencyProbe$UntrustedString\"}");
        reader = new org.apache.hadoop.shaded.org.apache.avro.specific.SpecificDatumReader<Object>(schema);
        decoder = org.apache.hadoop.shaded.org.apache.avro.io.DecoderFactory.get().jsonDecoder(schema, "\"blocked\"");
        denied = false;
        try { reader.read(null, decoder); }
        catch (SecurityException expected) { denied = true; }
        check(denied && UntrustedString.constructed == 0, "Avro untrusted class rejected before construction");

        var builder = Class.forName("org.openeo.geotrellis.OpenEOProcessScriptBuilder");
        check(builder.getDeclaredMethods().length > 0, "Upstream builder reflective linkage including CatBoost types");
        check("12.1.14".equals(org.sparkproject.jetty.util.Jetty.VERSION), "Actual Spark shaded Jetty version");
        for (String name : new String[]{"org.apache.commons.lang.ClassUtils", "org.apache.thrift.TException",
                "org.apache.hadoop.hive.ql.Driver", "org.apache.hadoop.shaded.org.eclipse.jetty.http.HttpURI",
                "org.apache.hadoop.shaded.org.jline.reader.LineReader"}) {
            denied = false;
            try { Class.forName(name); }
            catch (ClassNotFoundException expected) { denied = true; }
            check(denied, "Excluded component absent: " + name);
        }
        fs.close();
        System.out.println("CHECKS=" + checks);
    }
}
