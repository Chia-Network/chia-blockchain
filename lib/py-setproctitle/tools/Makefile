PTTEST_OBJS = pttest.o
SPTDEMO_OBJS = spt_demo.o ../src/spt_status.o ../src/strlcpy.o

PS_STATUS_C_URL = "http://git.postgresql.org/gitweb?p=postgresql.git;a=blob_plain;f=src/backend/utils/misc/ps_status.c;hb=HEAD"
PS_STATUS_H_URL = "http://git.postgresql.org/gitweb?p=postgresql.git;a=blob_plain;f=src/include/utils/ps_status.h;hb=HEAD"

CFLAGS = -g -Wall

CURL = wget -O -


all: pttest sptdemo prctl_demo

pttest: $(PTTEST_OBJS)

sptdemo: $(SPTDEMO_OBJS)
	$(CC) $(LDFLAGS) $^ -o $@

pgsources: ps_status.c ps_status.h

ps_status.c :
	$(CURL) $(PS_STATUS_C_URL) > $@

ps_status.h :
	$(CURL) $(PS_STATUS_H_URL) > $@

