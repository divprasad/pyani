#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""subcommands.py

Provides subcommand functions for the pyani.py script, and some helper

- download:      download assemblies from NCBI
- classify:      classify ANI results

The code in this module should mediate between the user via CLI and the actual
'lifting' code in the pyani module - it should not be implementing
calculations.

This module expects the use of a logger in function calls, as all functions
should only be called in the context of a CLI interaction with the user, and
this enforces logging.

(c) The James Hutton Institute 2017
Author: Leighton Pritchard
Contact: leighton.pritchard@hutton.ac.uk
Leighton Pritchard,
Information and Computing Sciences,
James Hutton Institute,
Errol Road,
Invergowrie,
Dundee,
DD6 9LH,
Scotland,
UK

The MIT License

Copyright (c) 2017 The James Hutton Institute
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""

import os
import shutil

from collections import namedtuple

from .. import __version__, download, pyani_tools, pyani_db
from . import tools


# Download sequence/class/label data from NCBI
def subcmd_download(args, logger):
    """Download all assembled genomes in the subtree of a passed NCBI taxon ID
    """
    # Create output directory, respecting force/noclobber
    tools.make_outdir(args.outdir, args.force, args.noclobber, logger)
    
    # Set Entrez email
    download.set_ncbi_email(args.email)
    logger.info("Setting Entrez email address: %s", args.email)
    
    # Get list of taxon IDs to download
    taxon_ids = download.split_taxa(args.taxon)
    logger.info("Taxon IDs received: %s", taxon_ids)

    # Get assembly UIDs for each taxon
    asm_dict = tools.make_asm_dict(taxon_ids, args.retries)
    for tid, uids in asm_dict.items():
        logger.info("Taxon ID summary\n\tQuery: " +\
                    "%s\n\tasm count: %s\n\tUIDs: %s", tid, len(uids), uids)


    # Compile list of outputs for class and label files, and a list of
    # skipped downloads (and a helper tuple for collating skipped genome
    # information)
    classes = []
    labels = []
    skippedlist = []
    Skipped = namedtuple("Skipped",
                         "taxon_id accession organism strain " +
                         "url dltype")

    # Download contigs and hashes for each assembly UID in the list
    for tid, uids in asm_dict.items():
        logger.info("Downloading contigs for Taxon ID %s", tid)
        for uid in uids:
            # Obtain eSummary            
            logger.info("Get eSummary information for UID %s", uid)
            esummary, filestem = download.get_ncbi_esummary(uid, args.retries)
            uid_class = download.get_ncbi_classification(esummary)

            # Report summary
            outstr = '\n\t'.join(["Taxid: %s" % esummary['SpeciesTaxid'],
                                  "Accession: %s" %
                                  esummary['AssemblyAccession'],
                                  "Name: %s" % esummary['AssemblyName'],
                                  "Organism: %s" % uid_class.organism,
                                  "Genus: %s" % uid_class.genus,
                                  "Species: %s" % uid_class.species,
                                  "Strain: %s" % uid_class.strain])
            logger.info("eSummary information:\n\t%s", outstr)

            # Make label/class text
            labeltxt, classtxt = download.create_labels(uid_class, filestem)
            classes.append(classtxt)
            labels.append(labeltxt)
            logger.info("Label and class file entries\n" + 
                        "\tLabel: %s\n\tClass: %s", labeltxt, classtxt)
    
            # Obtain URLs - trying the RefSeq filestem first
            ftpstem="ftp://ftp.ncbi.nlm.nih.gov/genomes/all"
            suffix="genomic.fna.gz"
            logger.info("Retrieving URLs for %s", filestem)
            # Try RefSeq first
            dlstatus = tools.download_genome_and_hash(filestem, suffix,
                                                      ftpstem, args.outdir,
                                                      args.timeout, logger,
                                                      dltype="RefSeq")
            if dlstatus.skipped:  # RefSeq failed, try GenBank
                logger.warning("RefSeq failed. Trying GenBank alternative " +
                               "assembly")
                skippedlist.append(Skipped(tid, uid,
                                           uid_class.organism,
                                           uid_class.strain,
                                           dlstatus.url, "RefSeq"))
                dlstatus = tools.download_genome_and_hash(filestem, suffix,
                                                          ftpstem, args.outdir,
                                                          args.timeout, logger,
                                                          dltype="GenBank")
                if dlstatus.skipped:
                    skippedlist.append(Skipped(tid, uid,
                                               uid_class.organism,
                                               uid_class.strain,
                                               dlstatus.url, "GenBank"))
                    continue  # Move straight on to the next download

            # Report the working download
            logger.info("Downloaded from URL: %s", dlstatus.url)
            logger.info("Wrote assembly to: %s", dlstatus.outfname)
            logger.info("Wrote MD5 hashes to: %s", dlstatus.outfhash)

            # Check hash for the download
            hashstatus = download.check_hash(dlstatus.outfname,
                                             dlstatus.outfhash)
            logger.info("Local MD5 hash: %s", hashstatus.localhash)
            logger.info("NCBI MD5 hash: %s", hashstatus.filehash)
            if hashstatus.passed:
                logger.info("MD5 hash check passed")
            else:
                logger.warning("MD5 hash check failed. Please check and retry.")

            # Extract downloaded files
            ename = os.path.splitext(dlstatus.outfname)[0]
            if os.path.exists(ename) and args.noclobber:
                logger.warning("Output file %s exists, not extracting", ename)
            else:
                logger.info("Extracting archive %s to %s",
                            dlstatus.outfname, ename)
                download.extract_contigs(dlstatus.outfname, ename)

            # Create MD5 hash for the downloaded contigs
            logger.info("Creating local MD5 hash for %s" % ename)
            hashfname = os.path.splitext(ename)[0] + '.md5'
            logger.info("Writing hash to %s" % hashfname)
            with open(hashfname, "w") as hfh:
                hfh.write('\t'.join([download.create_hash(ename),
                                     ename]) + '\n')
                
        
    # Write class and label files
    classfname = os.path.join(args.outdir, args.classfname)
    logger.info("Writing classes file to %s", classfname)
    if os.path.exists(classfname) and noclobber:
        logger.warning("Class file %s exists, not overwriting", classfname)
    else:
        with open(classfname, "w") as ofh:
            ofh.write('\n'.join(classes) + '\n')
    
    labelfname = os.path.join(args.outdir, args.labelfname)
    logger.info("Writing labels file to %s", labelfname)
    if os.path.exists(labelfname) and noclobber:
        logger.warning("Labels file %s exists, not overwriting", labelfname)
    else:
        with open(labelfname, "w") as ofh:
            ofh.write('\n'.join(labels) + '\n')

        
    # Show skipped genome list
    if len(skippedlist):
        logger.warning("%d genome downloads were skipped", len(skippedlist))
        for skipped in skippedlist:
            outstr = '\n\t'.join(["taxon id: %s" % skipped.taxon_id,
                                  "accession: %s" % skipped.accession,
                                  "URL: %s" % skipped.url,
                                  "source: %s" % skipped.dltype])
            logger.warning("%s %s:\n\t%s", skipped.organism, skipped.strain,
                           outstr)


# Generate MD5 hashes for each genome in an input directory
def subcmd_index(args, logger):
    """Generate an MD5 hash for each genome in an input directory.

    Identify the genome files in the input directory, and generate a single
    MD5 for each so that <genome>.fna produces <genome>.md5

    Genome files are identified from the file extension.
    """
    # Get list of FASTA files in the input directory
    logger.info("Scanning directory %s for FASTA files", args.indir)
    fnames = pyani_tools.get_fasta_paths(args.indir)
    logger.info('\n'.join(["Found FASTA files:"] +
                          ['\t' + fname for fname in fnames]))

    # Create MD5 hash for each file, if needed
    for fname in fnames:
        fpath = os.path.join(args.indir, fname)
        hashfname = os.path.splitext(fpath)[0] + '.md5'
        if os.path.isfile(hashfname):
            logger.info("%s already indexed (skipping)", fpath)
        else:
            logger.info("Writing hash to %s", hashfname)
            with open(hashfname, "w") as hfh:
                hfh.write('\t'.join([download.create_hash(fpath),
                                     fpath]) + '\n')


def subcmd_createdb(args, logger):
    """Create an empty pyani database."""
    # If the database exists, raise an error rather than overwrite
    if os.path.isfile(args.dbpath) and not args.force:
        logger.error("Database %s already exists (exiting)", args.dbpath)
        raise SystemError(1)
    # If the path to the database doesn't exist, create it
    dbdir = os.path.split(args.dbpath)[0]
    if not os.path.isdir(dbdir):
        logger.info("Creating database directory %s", dbdir)
        os.makedirs(dbdir, exist_ok=True)

    # Create the empty database
    logger.info("Creating pyani database at %s", args.dbpath)
    pyani_db.create_db(args.dbpath)
    

def subcmd_anim(args, logger):
    """Perform ANIm on all genome files in an input directory.
    """
    raise NotImplementedError


def subcmd_anib(args, logger):
    """Perform ANIm on all genome files in an input directory.
    """
    raise NotImplementedError


def subcmd_aniblastall(args, logger):
    """Perform ANIm on all genome files in an input directory.
    """
    raise NotImplementedError


def subcmd_render(args, logger):
    """Visualise ANI results for an analysis.
    """
    raise NotImplementedError
            
# Classify input genomes on basis of ANI coverage and identity output
def subcmd_classify(args, logger):
    """Take pyani output, and generate of classifications of the input data.
    """
    raise NotImplementedError