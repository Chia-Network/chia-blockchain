import os from 'os';

const homeDirectory = os.homedir();

export default function untildify(pathWithTilde: string): string {
	if (typeof pathWithTilde !== 'string') {
		throw new TypeError(`Expected a string, got ${typeof pathWithTilde}`);
	}

	return homeDirectory 
    ? pathWithTilde.replace(/^~(?=$|\/|\\)/, homeDirectory) 
    : pathWithTilde;
}
