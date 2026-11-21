/**
 * Entry module. It exports only the handler: the Workers runtime rejects any other named export
 * here ("Incorrect type for map entry"). The Worker itself is src/worker.ts.
 */
import { makeWorker } from "./worker";

export default makeWorker();
