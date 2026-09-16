"""Servizio HTTP: API a job + worker isolato.

Vive accanto alla libreria, non al posto suo: `docanalyzer.pipeline` non sa
che esiste, e la CLI resta il modo per fare debug di un singolo documento.
"""
